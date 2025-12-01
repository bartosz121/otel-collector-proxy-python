from http import HTTPStatus


def get_http_status_message(code: int) -> str:
    return HTTPStatus(code).phrase
