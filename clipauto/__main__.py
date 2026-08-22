import uvicorn

from clipauto.api import create_app
from clipauto.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
