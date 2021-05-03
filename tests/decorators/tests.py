import asyncio
from datetime import datetime
from functools import update_wrapper, wraps

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import (
    login_required, permission_required, user_passes_test,
)
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.middleware.clickjacking import XFrameOptionsMiddleware
from django.test import SimpleTestCase, TestCase
from django.utils.decorators import method_decorator
from django.utils.functional import keep_lazy, keep_lazy_text, lazy
from django.utils.safestring import mark_safe
from django.views.decorators.cache import (
    cache_control, cache_page, never_cache,
)
from django.views.decorators.clickjacking import (
    xframe_options_deny, xframe_options_exempt, xframe_options_sameorigin,
)
from django.views.decorators.csrf import (
    csrf_exempt, csrf_protect, ensure_csrf_cookie, requires_csrf_token,
)
from django.views.decorators.debug import (
    sensitive_post_parameters, sensitive_variables,
)
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import (
    condition, etag, last_modified, require_GET, require_http_methods,
    require_POST, require_safe,
)
from django.views.decorators.vary import vary_on_cookie, vary_on_headers


def fully_decorated(request):
    """Expected __doc__"""
    return HttpResponse('<html><body>dummy</body></html>')


fully_decorated.anything = "Expected __dict__"


def compose(*functions):
    # compose(f, g)(*args, **kwargs) == f(g(*args, **kwargs))
    functions = list(reversed(functions))

    def _inner(*args, **kwargs):
        result = functions[0](*args, **kwargs)
        for f in functions[1:]:
            result = f(result)
        return result
    return _inner


full_decorator = compose(
    # django.views.decorators.http
    require_http_methods(["GET"]),
    require_GET,
    require_POST,
    require_safe,
    condition(lambda r: None, lambda r: None),

    # django.views.decorators.vary
    vary_on_headers('Accept-language'),
    vary_on_cookie,

    # django.views.decorators.cache
    cache_page(60 * 15),
    cache_control(private=True),
    never_cache,

    # django.contrib.auth.decorators
    # Apply user_passes_test twice to check #9474
    user_passes_test(lambda u: True),
    login_required,
    permission_required('change_world'),

    # django.contrib.admin.views.decorators
    staff_member_required,

    # django.utils.functional
    keep_lazy(HttpResponse),
    keep_lazy_text,
    lazy,

    # django.utils.safestring
    mark_safe,
)

fully_decorated = full_decorator(fully_decorated)


class DecoratorsTest(TestCase):

    def test_attributes(self):
        """
        Built-in decorators set certain attributes of the wrapped function.
        """
        self.assertEqual(fully_decorated.__name__, 'fully_decorated')
        self.assertEqual(fully_decorated.__doc__, 'Expected __doc__')
        self.assertEqual(fully_decorated.__dict__['anything'], 'Expected __dict__')

    def test_user_passes_test_composition(self):
        """
        The user_passes_test decorator can be applied multiple times (#9474).
        """
        def test1(user):
            user.decorators_applied.append('test1')
            return True

        def test2(user):
            user.decorators_applied.append('test2')
            return True

        def callback(request):
            return request.user.decorators_applied

        callback = user_passes_test(test1)(callback)
        callback = user_passes_test(test2)(callback)

        class DummyUser:
            pass

        class DummyRequest:
            pass

        request = DummyRequest()
        request.user = DummyUser()
        request.user.decorators_applied = []
        response = callback(request)

        self.assertEqual(response, ['test2', 'test1'])

    def test_require_safe_accepts_only_safe_methods(self):
        """
        Test for the require_safe decorator.
        A view returns either a response or an exception.
        Refs #15637.
        """
        def my_view(request):
            return HttpResponse("OK")
        my_safe_view = require_safe(my_view)
        request = HttpRequest()
        request.method = 'GET'
        self.assertIsInstance(my_safe_view(request), HttpResponse)
        request.method = 'HEAD'
        self.assertIsInstance(my_safe_view(request), HttpResponse)
        request.method = 'POST'
        self.assertIsInstance(my_safe_view(request), HttpResponseNotAllowed)
        request.method = 'PUT'
        self.assertIsInstance(my_safe_view(request), HttpResponseNotAllowed)
        request.method = 'DELETE'
        self.assertIsInstance(my_safe_view(request), HttpResponseNotAllowed)

    async def test_async_require_http_methods_returns_coroutine(self):
        """
        Async Test for the require_http_methods decorator.
        Ensures async views are awaited and returned as coroutines while
        sync views return synchronously
        Refs #31949.
        """
        self.assertTrue(require_http_methods.async_capable)
        self.assertTrue(require_http_methods.sync_capable)

        @require_http_methods(["HEAD"])
        def my_sync_view(request):
            return HttpResponse("OK")

        @require_http_methods(["HEAD"])
        async def my_async_view(request):
            return HttpResponse("OK")

        self.assertFalse(asyncio.iscoroutinefunction(my_sync_view))
        self.assertTrue(asyncio.iscoroutinefunction(my_async_view))


# For testing method_decorator, a decorator that assumes a single argument.
# We will get type arguments if there is a mismatch in the number of arguments.
def simple_dec(func):
    def wrapper(arg):
        return func("test:" + arg)
    return wraps(func)(wrapper)


simple_dec_m = method_decorator(simple_dec)


# For testing method_decorator, two decorators that add an attribute to the function
def myattr_dec(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    wrapper.myattr = True
    return wrapper


myattr_dec_m = method_decorator(myattr_dec)


def myattr2_dec(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    wrapper.myattr2 = True
    return wrapper


myattr2_dec_m = method_decorator(myattr2_dec)


class ClsDec:
    def __init__(self, myattr):
        self.myattr = myattr

    def __call__(self, f):

        def wrapped():
            return f() and self.myattr
        return update_wrapper(wrapped, f)


class MethodDecoratorTests(SimpleTestCase):
    """
    Tests for method_decorator
    """
    def test_preserve_signature(self):
        class Test:
            @simple_dec_m
            def say(self, arg):
                return arg

        self.assertEqual("test:hello", Test().say("hello"))

    def test_preserve_attributes(self):
        # Sanity check myattr_dec and myattr2_dec
        @myattr_dec
        def func():
            pass
        self.assertIs(getattr(func, 'myattr', False), True)

        @myattr2_dec
        def func():
            pass
        self.assertIs(getattr(func, 'myattr2', False), True)

        @myattr_dec
        @myattr2_dec
        def func():
            pass

        self.assertIs(getattr(func, 'myattr', False), True)
        self.assertIs(getattr(func, 'myattr2', False), False)

        # Decorate using method_decorator() on the method.
        class TestPlain:
            @myattr_dec_m
            @myattr2_dec_m
            def method(self):
                "A method"
                pass

        # Decorate using method_decorator() on both the class and the method.
        # The decorators applied to the methods are applied before the ones
        # applied to the class.
        @method_decorator(myattr_dec_m, "method")
        class TestMethodAndClass:
            @method_decorator(myattr2_dec_m)
            def method(self):
                "A method"
                pass

        # Decorate using an iterable of function decorators.
        @method_decorator((myattr_dec, myattr2_dec), 'method')
        class TestFunctionIterable:
            def method(self):
                "A method"
                pass

        # Decorate using an iterable of method decorators.
        decorators = (myattr_dec_m, myattr2_dec_m)

        @method_decorator(decorators, "method")
        class TestMethodIterable:
            def method(self):
                "A method"
                pass

        tests = (TestPlain, TestMethodAndClass, TestFunctionIterable, TestMethodIterable)
        for Test in tests:
            with self.subTest(Test=Test):
                self.assertIs(getattr(Test().method, 'myattr', False), True)
                self.assertIs(getattr(Test().method, 'myattr2', False), True)
                self.assertIs(getattr(Test.method, 'myattr', False), True)
                self.assertIs(getattr(Test.method, 'myattr2', False), True)
                self.assertEqual(Test.method.__doc__, 'A method')
                self.assertEqual(Test.method.__name__, 'method')

    def test_new_attribute(self):
        """A decorator that sets a new attribute on the method."""
        def decorate(func):
            func.x = 1
            return func

        class MyClass:
            @method_decorator(decorate)
            def method(self):
                return True

        obj = MyClass()
        self.assertEqual(obj.method.x, 1)
        self.assertIs(obj.method(), True)

    def test_bad_iterable(self):
        decorators = {myattr_dec_m, myattr2_dec_m}
        msg = "'set' object is not subscriptable"
        with self.assertRaisesMessage(TypeError, msg):
            @method_decorator(decorators, "method")
            class TestIterable:
                def method(self):
                    "A method"
                    pass

    # Test for argumented decorator
    def test_argumented(self):
        class Test:
            @method_decorator(ClsDec(False))
            def method(self):
                return True

        self.assertIs(Test().method(), False)

    def test_descriptors(self):

        def original_dec(wrapped):
            def _wrapped(arg):
                return wrapped(arg)

            return _wrapped

        method_dec = method_decorator(original_dec)

        class bound_wrapper:
            def __init__(self, wrapped):
                self.wrapped = wrapped
                self.__name__ = wrapped.__name__

            def __call__(self, arg):
                return self.wrapped(arg)

            def __get__(self, instance, cls=None):
                return self

        class descriptor_wrapper:
            def __init__(self, wrapped):
                self.wrapped = wrapped
                self.__name__ = wrapped.__name__

            def __get__(self, instance, cls=None):
                return bound_wrapper(self.wrapped.__get__(instance, cls))

        class Test:
            @method_dec
            @descriptor_wrapper
            def method(self, arg):
                return arg

        self.assertEqual(Test().method(1), 1)

    def test_class_decoration(self):
        """
        @method_decorator can be used to decorate a class and its methods.
        """
        def deco(func):
            def _wrapper(*args, **kwargs):
                return True
            return _wrapper

        @method_decorator(deco, name="method")
        class Test:
            def method(self):
                return False

        self.assertTrue(Test().method())

    def test_tuple_of_decorators(self):
        """
        @method_decorator can accept a tuple of decorators.
        """
        def add_question_mark(func):
            def _wrapper(*args, **kwargs):
                return func(*args, **kwargs) + "?"
            return _wrapper

        def add_exclamation_mark(func):
            def _wrapper(*args, **kwargs):
                return func(*args, **kwargs) + "!"
            return _wrapper

        # The order should be consistent with the usual order in which
        # decorators are applied, e.g.
        #    @add_exclamation_mark
        #    @add_question_mark
        #    def func():
        #        ...
        decorators = (add_exclamation_mark, add_question_mark)

        @method_decorator(decorators, name="method")
        class TestFirst:
            def method(self):
                return "hello world"

        class TestSecond:
            @method_decorator(decorators)
            def method(self):
                return "hello world"

        self.assertEqual(TestFirst().method(), "hello world?!")
        self.assertEqual(TestSecond().method(), "hello world?!")

    def test_invalid_non_callable_attribute_decoration(self):
        """
        @method_decorator on a non-callable attribute raises an error.
        """
        msg = (
            "Cannot decorate 'prop' as it isn't a callable attribute of "
            "<class 'Test'> (1)"
        )
        with self.assertRaisesMessage(TypeError, msg):
            @method_decorator(lambda: None, name="prop")
            class Test:
                prop = 1

                @classmethod
                def __module__(cls):
                    return "tests"

    def test_invalid_method_name_to_decorate(self):
        """
        @method_decorator on a nonexistent method raises an error.
        """
        msg = (
            "The keyword argument `name` must be the name of a method of the "
            "decorated class: <class 'Test'>. Got 'nonexistent_method' instead"
        )
        with self.assertRaisesMessage(ValueError, msg):
            @method_decorator(lambda: None, name='nonexistent_method')
            class Test:
                @classmethod
                def __module__(cls):
                    return "tests"


class SyncAndAsyncMiddlewareTests(TestCase):
    """
    Tests to make sure all builtin decorators declare themselves as sync and
    async capable.
    """
    def test_cache_page_decorator(self):
        self.assertTrue(cache_control.sync_capable)
        self.assertTrue(cache_control.async_capable)

    def test_cache_control_decorator(self):
        self.assertTrue(cache_control.sync_capable)
        self.assertTrue(cache_control.async_capable)

    def test_never_cache_decorator(self):
        self.assertTrue(never_cache.sync_capable)
        self.assertTrue(never_cache.async_capable)

    def test_xframe_options_deny_decorator(self):
        self.assertTrue(xframe_options_deny.sync_capable)
        self.assertTrue(xframe_options_deny.async_capable)

    def test_xframe_options_sameorigin_decorator(self):
        self.assertTrue(xframe_options_sameorigin.sync_capable)
        self.assertTrue(xframe_options_sameorigin.async_capable)

    def test_xframe_options_exempt_decorator(self):
        self.assertTrue(xframe_options_exempt.sync_capable)
        self.assertTrue(xframe_options_exempt.async_capable)

    def test_csrf_protect_decorator(self):
        self.assertTrue(csrf_protect.sync_capable)
        self.assertTrue(csrf_protect.async_capable)

    def test_requires_csrf_token_decorator(self):
        self.assertTrue(requires_csrf_token.sync_capable)
        self.assertTrue(requires_csrf_token.async_capable)

    def test_ensure_csrf_cookie_decorator(self):
        self.assertTrue(ensure_csrf_cookie.sync_capable)
        self.assertTrue(ensure_csrf_cookie.async_capable)

    def test_csrf_exempt_decorator(self):
        self.assertTrue(csrf_exempt.sync_capable)
        self.assertTrue(csrf_exempt.async_capable)

    def test_sensitive_variables_decorator(self):
        self.assertTrue(sensitive_variables.sync_capable)
        self.assertTrue(sensitive_variables.async_capable)

    def test_sensitive_post_parameters_decorator(self):
        self.assertTrue(sensitive_post_parameters.sync_capable)
        self.assertTrue(sensitive_post_parameters.async_capable)

    def test_gzip_page_decorator(self):
        self.assertTrue(gzip_page.sync_capable)
        self.assertTrue(gzip_page.async_capable)

    def test_require_http_methods_decorator(self):
        self.assertTrue(require_http_methods.sync_capable)
        self.assertTrue(require_http_methods.async_capable)

    def test_require_GET_decorator(self):
        self.assertTrue(require_GET.sync_capable)
        self.assertTrue(require_GET.async_capable)

    def test_require_POST_decorator(self):
        self.assertTrue(require_POST.sync_capable)
        self.assertTrue(require_POST.async_capable)

    def test_require_safe_decorator(self):
        self.assertTrue(require_safe.sync_capable)
        self.assertTrue(require_safe.async_capable)

    def test_condition_decorator(self):
        self.assertTrue(condition.sync_capable)
        self.assertTrue(condition.async_capable)

    def test_etag_decorator(self):
        self.assertTrue(etag.sync_capable)
        self.assertTrue(etag.async_capable)

    def test_last_modified_decorator(self):
        self.assertTrue(last_modified.sync_capable)
        self.assertTrue(last_modified.async_capable)

    def test_vary_on_headers_decorator(self):
        self.assertTrue(vary_on_headers.sync_capable)
        self.assertTrue(vary_on_headers.async_capable)

    def test_vary_on_cookie_decorator(self):
        self.assertTrue(vary_on_cookie.sync_capable)
        self.assertTrue(vary_on_cookie.async_capable)


class XFrameOptionsDecoratorsTests(TestCase):
    """
    Tests for the X-Frame-Options decorators.
    """
    def test_deny_decorator_sets_x_frame_options_header(self):
        @xframe_options_deny
        def a_view(request):
            return HttpResponse()
        response = a_view(HttpRequest())
        self.assertEqual(response.get('X-Frame-Options'), 'DENY')

    async def test_deny_decorator_sets_x_frame_options_header_with_async_view(self):
        @xframe_options_deny
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(HttpRequest())
        self.assertEqual(response.get('X-Frame-Options'), 'DENY')

    def test_sameorigin_decorator_sets_x_frame_options_header(self):
        @xframe_options_sameorigin
        def a_view(request):
            return HttpResponse()
        response = a_view(HttpRequest())
        self.assertEqual(response.get('X-Frame-Options'), 'SAMEORIGIN')

    async def test_sameorigin_decorator_sets_x_frame_options_header_with_async_view(self):
        @xframe_options_sameorigin
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(HttpRequest())
        self.assertEqual(response.get('X-Frame-Options'), 'SAMEORIGIN')

    def test_exempt_decorator_does_not_set_x_frame_options_header(self):
        """
        Ensures @xframe_options_exempt instructs the XFrameOptionsMiddleware to NOT set
        the header.
        """
        @xframe_options_exempt
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        response = a_view(request)
        self.assertIsNone(response.get('X-Frame-Options'))
        self.assertTrue(response.xframe_options_exempt)

        # Since the real purpose of the exempt decorator is to suppress
        # the middleware's functionality, let's make sure it actually works...
        response = XFrameOptionsMiddleware(a_view)(request)
        self.assertIsNone(response.get('X-Frame-Options'))

    async def test_exempt_decorator_does_not_set_x_frame_options_header_with_async_view(self):
        """
        Ensures @xframe_options_exempt instructs the XFrameOptionsMiddleware to NOT set
        the header for an async view.
        """
        @xframe_options_exempt
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        response = await an_async_view(request)
        self.assertIsNone(response.get('X-Frame-Options'))
        self.assertTrue(response.xframe_options_exempt)

        # Since the real purpose of the exempt decorator is to suppress
        # the middleware's functionality, let's make sure it actually works...
        response = await XFrameOptionsMiddleware(an_async_view)(request)
        self.assertIsNone(response.get('X-Frame-Options'))


class CacheDecoratorTest(TestCase):
    """
    Tests for the caching decorators.
    """
    def test_cache_page_decorator(self):
        @cache_page(123)
        def a_view(request):
            return 'response'
        response = a_view(HttpRequest())
        self.assertEqual(response, 'response')

    async def test_cache_page_decorator_with_async_view(self):
        @cache_page(123)
        async def an_async_view(request):
            return 'response'
        response = await an_async_view(HttpRequest())
        self.assertEqual(response, 'response')

    def test_cache_page_decorator_with_key_prefix(self):
        @cache_page(123, key_prefix='test')
        def a_view(request):
            return 'response'
        response = a_view(HttpRequest())
        self.assertEqual(response, 'response')

    async def test_cache_page_decorator_with_key_prefix_with_async_view(self):
        @cache_page(123, key_prefix='test')
        async def an_async_view(request):
            return 'response'
        response = await an_async_view(HttpRequest())
        self.assertEqual(response, 'response')

    def test_cache_control_empty_decorator(self):
        @cache_control()
        def a_view(request):
            return HttpResponse()
        response = a_view(HttpRequest())
        self.assertEqual(response.get('Cache-Control'), '')

    async def test_cache_control_empty_decorator_with_async_view(self):
        @cache_control()
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(HttpRequest())
        self.assertEqual(response.get('Cache-Control'), '')

    def test_cache_control_full_decorator(self):
        @cache_control(max_age=123, private=True, public=True, custom=456)
        def a_view(request):
            return HttpResponse()
        response = a_view(HttpRequest())
        cache_control_items = response.get('Cache-Control').split(', ')
        self.assertEqual(
            set(cache_control_items),
            {'max-age=123', 'private', 'public', 'custom=456'}
        )

    async def test_cache_control_full_decorator_with_async_view(self):
        @cache_control(max_age=123, private=True, public=True, custom=456)
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(HttpRequest())
        cache_control_items = response.get('Cache-Control').split(', ')
        self.assertEqual(
            set(cache_control_items),
            {'max-age=123', 'private', 'public', 'custom=456'}
        )


class NeverCacheDecoratorTest(SimpleTestCase):
    def test_never_cache_decorator(self):
        @never_cache
        def a_view(request):
            return HttpResponse()
        response = a_view(HttpRequest())
        cache_control_items = response.get('Cache-Control').split(', ')
        self.assertEqual(
            set(cache_control_items),
            {'max-age=0', 'no-cache', 'no-store', 'must-revalidate', 'private'},
        )

    def test_never_cache_decorator_http_request(self):
        class MyClass:
            @never_cache
            def a_view(self, request):
                return HttpResponse()
        msg = (
            "never_cache didn't receive an HttpRequest. If you are decorating "
            "a classmethod, be sure to use @method_decorator."
        )
        with self.assertRaisesMessage(TypeError, msg):
            MyClass().a_view(HttpRequest())

    async def test_never_cache_decorator_with_async_view(self):
        @never_cache
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(HttpRequest())
        cache_control_items = response.get('Cache-Control').split(', ')
        self.assertEqual(
            set(cache_control_items),
            {'max-age=0', 'no-cache', 'no-store', 'must-revalidate', 'private'},
        )


class CacheControlDecoratorTest(SimpleTestCase):
    def test_cache_control_decorator_http_request(self):
        class MyClass:
            @cache_control(a='b')
            def a_view(self, request):
                return HttpResponse()

        msg = (
            "cache_control didn't receive an HttpRequest. If you are "
            "decorating a classmethod, be sure to use @method_decorator."
        )
        with self.assertRaisesMessage(TypeError, msg):
            MyClass().a_view(HttpRequest())


class CsrfDecoratorTest(TestCase):

    csrf_token = '1bcdefghij2bcdefghij3bcdefghij4bcdefghij5bcdefghij6bcdefghijABCD'

    def setUp(self):
        # Use request that will trigger the middleware but has a csrf token
        self.request = HttpRequest()
        self.request.method = 'POST'
        self.request.POST['csrfmiddlewaretoken'] = self.csrf_token
        self.request.COOKIES['csrftoken'] = self.csrf_token

    def test_csrf_protect_decorator(self):
        @csrf_protect
        def a_view(request):
            return HttpResponse()
        response = a_view(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.request.csrf_processing_done)

    async def test_csrf_protect_decorator_with_async_view(self):
        @csrf_protect
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.request.csrf_processing_done)

    def test_requires_csrf_token_decorator(self):
        @requires_csrf_token
        def a_view(request):
            return HttpResponse()
        response = a_view(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.request.csrf_processing_done)

    async def test_requires_csrf_token_decorator_with_async_view(self):
        @requires_csrf_token
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.request.csrf_processing_done)

    def test_ensure_csrf_cookie_decorator(self):
        @ensure_csrf_cookie
        def a_view(request):
            return HttpResponse()
        response = a_view(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.request.csrf_processing_done)

    async def test_ensure_csrf_cookie_decorator_with_async_view(self):
        @ensure_csrf_cookie
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.request.csrf_processing_done)

    def test_csrf_exempt_decorator(self):
        @csrf_exempt
        def a_view(request):
            return HttpResponse()
        response = a_view(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(hasattr(self.request, 'csrf_processing_done'))

    async def test_csrf_exempt_decorator_with_async_view(self):
        @csrf_exempt
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(hasattr(self.request, 'csrf_processing_done'))


class DebugDecoratorsTests(TestCase):
    """
    Tests for the debug decorators.
    """
    def test_sensitive_variables_decorator(self):
        @sensitive_variables()
        def a_func():
            return 'result'
        # The decorator takes effect when the function is called
        result = a_func()
        self.assertEqual(result, 'result')
        self.assertEqual(a_func.sensitive_variables, '__ALL__')

    async def test_sensitive_variables_decorator_with_async_function(self):
        @sensitive_variables()
        async def an_async_func():
            return 'result'
        # The decorator takes effect when the function is called
        result = await an_async_func()
        self.assertEqual(result, 'result')
        self.assertEqual(an_async_func.sensitive_variables, '__ALL__')

    def test_sensitive_post_parameters_decorator(self):
        @sensitive_post_parameters()
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        response = a_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.sensitive_post_parameters, '__ALL__')

    async def test_sensitive_post_parameters_decorator_with_async_view(self):
        @sensitive_post_parameters()
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.sensitive_post_parameters, '__ALL__')


class GzipDecoratorsTests(TestCase):
    """
    Tests for the gzip decorator.
    """
    # Gzip ignores content that is too short
    content = "Content " * 100

    def test_gzip_decorator(self):
        @gzip_page
        def a_view(request):
            return HttpResponse(content=self.content)
        request = HttpRequest()
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        response = a_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get('Content-Encoding'), 'gzip')

    async def test_gzip_decorator_with_async_view(self):
        @gzip_page
        async def an_async_view(request):
            return HttpResponse(content=self.content)
        request = HttpRequest()
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get('Content-Encoding'), 'gzip')


class VaryDecoratorsTests(TestCase):
    """
    Tests for the vary decorator.
    """
    def test_vary_on_headers_decorator(self):
        @vary_on_headers('Header', 'Another-header')
        def a_view(request):
            return HttpResponse()
        response = a_view(HttpRequest())
        self.assertEqual(response.status_code, 200)
        # Assert each decorator argument is in the response header
        vary_items_set = {item.strip() for item in response.get('Vary').split(',')}
        self.assertIn('Header', vary_items_set)
        self.assertIn('Another-header', vary_items_set)

    async def test_vary_on_headers_decorator_with_async_view(self):
        @vary_on_headers('Header', 'Another-header')
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(HttpRequest())
        self.assertEqual(response.status_code, 200)
        # Assert each decorator argument is in the response header
        vary_items_set = {item.strip() for item in response.get('Vary').split(',')}
        self.assertIn('Header', vary_items_set)
        self.assertIn('Another-header', vary_items_set)

    def test_vary_on_cookie_decorator(self):
        @vary_on_cookie
        def a_view(request):
            return HttpResponse()
        response = a_view(HttpRequest())
        self.assertEqual(response.status_code, 200)
        vary_items_set = {item.strip() for item in response.get('Vary').split(',')}
        self.assertIn('Cookie', vary_items_set)

    async def test_vary_on_cookie_decorator_with_async_view(self):
        @vary_on_cookie
        async def an_async_view(request):
            return HttpResponse()
        response = await an_async_view(HttpRequest())
        self.assertEqual(response.status_code, 200)
        self.assertIn('Cookie', response.get('Vary'))
        vary_items_set = {item.strip() for item in response.get('Vary').split(',')}
        self.assertIn('Cookie', vary_items_set)


class ConditionalDecoratorTests(TestCase):
    """
    Tests for the conditional decorators.
    """
    def etag_func(self, request, *args, **kwargs):
        return '"abc123"'

    def last_modified_func(self, request, *args, **kwargs):
        return datetime(2020, 1, 1)

    def test_etag_decorator_match_all(self):
        @etag(etag_func=self.etag_func)
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.META['HTTP_IF_MATCH'] = '*'
        response = a_view(request)
        self.assertEqual(response.status_code, 200)

    async def test_etag_decorator_match_all_with_async_view(self):
        @etag(etag_func=self.etag_func)
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.META['HTTP_IF_MATCH'] = '*'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 200)

    def test_etag_decorator_no_match(self):
        @etag(etag_func=self.etag_func)
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.META['HTTP_IF_MATCH'] = '"def456"'
        response = a_view(request)
        self.assertEqual(response.status_code, 412)

    async def test_etag_decorator_no_match_with_async_view(self):
        @etag(etag_func=self.etag_func)
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.META['HTTP_IF_MATCH'] = '"def456"'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 412)

    def test_etag_decorator_not_modified(self):
        @etag(etag_func=self.etag_func)
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'GET'
        request.META['HTTP_IF_NONE_MATCH'] = '*'
        response = a_view(request)
        self.assertEqual(response.status_code, 304)

    async def test_etag_decorator_not_modified_with_async_view(self):
        @etag(etag_func=self.etag_func)
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'GET'
        request.META['HTTP_IF_NONE_MATCH'] = '*'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 304)

    def test_last_modified_decorator_modified_since(self):
        @last_modified(last_modified_func=self.last_modified_func)
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        # One day BEFORE the last_modified_func datetime
        request.META['HTTP_IF_MODIFIED_SINCE'] = 'Tue, 31 Dec 2019 00:00:00 GMT'
        response = a_view(request)
        self.assertEqual(response.status_code, 200)

    async def test_last_modified_decorator_modified_since_with_async_view(self):
        @last_modified(last_modified_func=self.last_modified_func)
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        # One day BEFORE the last_modified_func datetime
        request.META['HTTP_IF_MODIFIED_SINCE'] = 'Tue, 31 Dec 2019 00:00:00 GMT'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 200)

    def test_last_modified_decorator_not_modified_since(self):
        @last_modified(last_modified_func=self.last_modified_func)
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'GET'
        # One day AFTER the last_modified_func datetime
        request.META['HTTP_IF_MODIFIED_SINCE'] = 'Thu, 02 Jan 2020 00:00:00 GMT'
        response = a_view(request)
        self.assertEqual(response.status_code, 304)

    async def test_last_modified_decorator_not_modified_since_with_async_view(self):
        @last_modified(last_modified_func=self.last_modified_func)
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'GET'
        # One day AFTER the last_modified_func datetime
        request.META['HTTP_IF_MODIFIED_SINCE'] = 'Thu, 02 Jan 2020 00:00:00 GMT'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 304)

    def test_condition_decorator_match_all(self):
        @condition(
            etag_func=self.etag_func,
            last_modified_func=self.last_modified_func,
        )
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.META['HTTP_IF_MATCH'] = '*'
        # One day BEFORE the last_modified_func datetime
        request.META['HTTP_IF_MODIFIED_SINCE'] = 'Tue, 31 Dec 2019 00:00:00 GMT'
        response = a_view(request)
        self.assertEqual(response.status_code, 200)

    async def test_condition_decorator_match_all_with_async_view(self):
        @condition(
            etag_func=self.etag_func,
            last_modified_func=self.last_modified_func,
        )
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.META['HTTP_IF_MATCH'] = '*'
        # One day BEFORE the last_modified_func datetime
        request.META['HTTP_IF_MODIFIED_SINCE'] = 'Tue, 31 Dec 2019 00:00:00 GMT'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 200)


class RequireHttpMethodsDecoratorTests(TestCase):
    def test_require_get_decorator_successful(self):
        @require_GET
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'GET'
        response = a_view(request)
        self.assertEqual(response.status_code, 200)

    async def test_require_get_decorator_successful_with_async_view(self):
        @require_GET
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'GET'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 200)

    def test_require_get_decorator_unsuccessful(self):
        @require_GET
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'POST'
        response = a_view(request)
        self.assertEqual(response.status_code, 405)

    async def test_require_get_decorator_unsuccessful_with_async_view(self):
        @require_GET
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'POST'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 405)

    def test_require_post_decorator_successful(self):
        @require_POST
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'POST'
        response = a_view(request)
        self.assertEqual(response.status_code, 200)

    async def test_require_post_decorator_successful_with_async_view(self):
        @require_POST
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'POST'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 200)

    def test_require_post_decorator_unsuccessful(self):
        @require_POST
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'GET'
        response = a_view(request)
        self.assertEqual(response.status_code, 405)

    async def test_require_post_decorator_unsuccessful_with_async_view(self):
        @require_POST
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'GET'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 405)

    def test_require_safe_decorator_successful(self):
        @require_safe
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        # Only GET and HEAD are safe methods
        request.method = 'HEAD'
        response = a_view(request)
        self.assertEqual(response.status_code, 200)

    async def test_require_safe_decorator_successful_with_async_view(self):
        @require_safe
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        # Only GET and HEAD are safe methods
        request.method = 'HEAD'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 200)

    def test_require_safe_decorator_unsuccessful(self):
        @require_safe
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        # Only GET and HEAD are safe methods
        request.method = 'POST'
        response = a_view(request)
        self.assertEqual(response.status_code, 405)

    async def test_require_safe_decorator_unsuccessful_with_async_view(self):
        @require_safe
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        # Only GET and HEAD are safe methods
        request.method = 'POST'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 405)

    def test_require_http_methods_decorator_successful(self):
        @require_http_methods(['HEAD'])
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'HEAD'
        response = a_view(request)
        self.assertEqual(response.status_code, 200)

    async def test_require_http_methods_decorator_successful_with_async_view(self):
        @require_http_methods(['HEAD'])
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'HEAD'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 200)

    def test_require_http_methods_decorator_unsuccessful(self):
        @require_http_methods(['HEAD'])
        def a_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'GET'
        response = a_view(request)
        self.assertEqual(response.status_code, 405)

    async def test_require_http_methods_decorator_unsuccessful_with_async_view(self):
        @require_http_methods(['HEAD'])
        async def an_async_view(request):
            return HttpResponse()
        request = HttpRequest()
        request.method = 'GET'
        response = await an_async_view(request)
        self.assertEqual(response.status_code, 405)
