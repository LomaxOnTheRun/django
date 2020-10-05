from django.utils.cache import patch_vary_headers
from django.utils.decorators import (
    sync_and_async_middleware, sync_async_wrapper,
)


@sync_and_async_middleware
def vary_on_headers(*headers):
    """
    A view decorator that adds the specified headers to the Vary header of the
    response. Usage:

       @vary_on_headers('Cookie', 'Accept-language')
       def index(request):
           ...

    Note that the header names are not case-sensitive.
    """
    def decorator(view_func):
        def process_response(response):
            patch_vary_headers(response, headers)
            return response
        return sync_async_wrapper(view_func, process_response=process_response)
    return decorator


@sync_and_async_middleware
def vary_on_cookie(view_func):
    """
    A view decorator that adds "Cookie" to the Vary header of a response. This
    indicates that a page's contents depends on cookies. Usage:

        @vary_on_cookie
        def index(request):
            ...
    """
    def process_response(response):
        patch_vary_headers(response, ('Cookie',))
        return response
    return sync_async_wrapper(view_func, process_response=process_response)
