from drf_yasg.utils import swagger_auto_schema


def get_swagger_response_dict(
    api_exceptions=None,
    success_response=None,
) -> str:
    """
    Build the responses argument for swagger_auto_schema so it renders clearly in Swagger.
    :param api_exceptions: List of all exceptions that can occur in the view
    :param success_response: Dict of success HTTP codes and response serializers
    :return:
    """
    if success_response:
        result = success_response
    else:
        result = {}
    api_exception_str_info = {}

    if api_exceptions:
        for api_exception in api_exceptions:
            if api_exception.status_code in api_exception_str_info.keys():
                api_exception_str_info[
                    api_exception.status_code
                ] += f'{{"detail" : "{api_exception.default_detail}"}} // {api_exception.swagger_description}\n\n'
            else:
                api_exception_str_info[api_exception.status_code] = (
                    f'{{"detail" : "{api_exception.default_detail}"}} // {api_exception.swagger_description}\n\n'
                )
        for k, v in api_exception_str_info.items():
            result[k] = v
    return result


def custom_swagger_auto_schema(**kwargs):
    return swagger_auto_schema(**kwargs)
