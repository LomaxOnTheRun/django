from django.http import HttpRequest
from django.middleware.cache import CacheMiddleware
from django.utils.cache import add_never_cache_headers, patch_cache_control
from django.utils.decorators import (
    decorator_from_middleware_with_args, sync_and_async_middleware,
    sync_async_wrapper,
)


@sync_and_async_middleware
def cache_page(timeout, *, cache=None, key_prefix=None):
    """
    Decorator for views that tries getting the page from the cache and
    populates the cache if the page isn't in the cache yet.

    The cache is keyed by the URL and some data from the headers.
    Additionally there is the key prefix that is used to distinguish different
    cache areas in a multi-site setup. You could use the
    get_current_site().domain, for example, as that is unique across a Django
    project.

    Additionally, all headers from the response's Vary header will be taken
    into account on caching -- just like the middleware does.
    """
    return decorator_from_middleware_with_args(CacheMiddleware)(
        page_timeout=timeout, cache_alias=cache, key_prefix=key_prefix,
    )


@sync_and_async_middleware
def cache_control(**decorator_kwargs):
    def _cache_controller(view_func):
        def process_request(request):
            if not isinstance(request, HttpRequest):
                raise TypeError(
                    "cache_control didn't receive an HttpRequest. If you are "
                    "decorating a classmethod, be sure to use "
                    "@method_decorator."
                )
            return request

        def process_response(response, **decorator_kwargs):
            patch_cache_control(response, **decorator_kwargs)
            return response

        return sync_async_wrapper(
            view_func,
            process_request=process_request,
            process_response=process_response,
            **decorator_kwargs,
        )

    return _cache_controller


@sync_and_async_middleware
def never_cache(view_func):
    """
    Decorator that adds headers to a response so that it will never be cached.
    """

    def process_request(request):
        if not isinstance(request, HttpRequest):
            raise TypeError(
                "never_cache didn't receive an HttpRequest. If you are "
                "decorating a classmethod, be sure to use @method_decorator."
            )
        return request

    def process_response(response):
        add_never_cache_headers(response)
        return response

    return sync_async_wrapper(
        view_func, process_request=process_request, process_response=process_response
    )
