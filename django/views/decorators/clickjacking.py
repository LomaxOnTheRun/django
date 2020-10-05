from django.utils.decorators import (
    sync_and_async_middleware, sync_async_wrapper,
)


@sync_and_async_middleware
def xframe_options_deny(view_func):
    """
    Modify a view function so its response has the X-Frame-Options HTTP
    header set to 'DENY' as long as the response doesn't already have that
    header set. Usage:

    @xframe_options_deny
    def some_view(request):
        ...
    """
    def process_response(response):
        if response.get('X-Frame-Options') is None:
            response['X-Frame-Options'] = 'DENY'
        return response
    return sync_async_wrapper(view_func, process_response=process_response)


@sync_and_async_middleware
def xframe_options_sameorigin(view_func):
    """
    Modify a view function so its response has the X-Frame-Options HTTP
    header set to 'SAMEORIGIN' as long as the response doesn't already have
    that header set. Usage:

    @xframe_options_sameorigin
    def some_view(request):
        ...
    """
    def process_response(response):
        if response.get('X-Frame-Options') is None:
            response['X-Frame-Options'] = 'SAMEORIGIN'
        return response
    return sync_async_wrapper(view_func, process_response=process_response)


@sync_and_async_middleware
def xframe_options_exempt(view_func):
    """
    Modify a view function by setting a response variable that instructs
    XFrameOptionsMiddleware to NOT set the X-Frame-Options HTTP header. Usage:

    @xframe_options_exempt
    def some_view(request):
        ...
    """
    def process_response(response):
        response.xframe_options_exempt = True
        return response
    return sync_async_wrapper(view_func, process_response=process_response)
