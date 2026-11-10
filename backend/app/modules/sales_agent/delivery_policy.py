"""A missing transport receipt never authorizes an automatic second send."""
import httpx
from fastapi import HTTPException


class DeliveryUncertainError(RuntimeError):
    pass


def uncertain(exception):
    return (isinstance(exception,httpx.RequestError) or
        isinstance(exception,httpx.HTTPStatusError) and exception.response.status_code>=500 or
        isinstance(exception,HTTPException) and exception.status_code>=500)
