from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.database import engine
from backend.models import Base
from backend.routers.auth import is_authenticated
from backend.routers.caixas_email import router as caixas_email_router
from backend.routers.criar_empresa import router as criar_empresa_router
from backend.routers.dominios import router as dominios_router
from backend.routers.login import router as login_router
from backend.routers.webmail import router as webmail_router

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"

app = FastAPI(
    title="AureMail",
    version="0.1.0",
)

Base.metadata.create_all(bind=engine)

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

app.include_router(login_router)
app.include_router(criar_empresa_router)
app.include_router(dominios_router)
app.include_router(webmail_router)
app.include_router(caixas_email_router)


def frontend_file(filename: str) -> Path:
    return FRONTEND_DIR / filename


def serve_page(
    request: Request,
    filename: str,
    require_auth: bool = False,
    redirect_if_logged: str | None = None,
):
    if require_auth and not is_authenticated(request):
        return RedirectResponse(url="/login")

    if redirect_if_logged and is_authenticated(request):
        return RedirectResponse(url=redirect_if_logged)

    file_path = frontend_file(filename)
    if not file_path.exists():
        return RedirectResponse(url="/login")

    return FileResponse(file_path)


@app.get("/", include_in_schema=False)
def root(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/app")
    return RedirectResponse(url="/login")


@app.get("/login", include_in_schema=False)
@app.get("/login.html", include_in_schema=False)
def login_page(request: Request):
    return serve_page(
        request=request,
        filename="login.html",
        require_auth=False,
        redirect_if_logged="/app",
    )


@app.get("/criar-empresa", include_in_schema=False)
@app.get("/criar-empresa.html", include_in_schema=False)
def criar_empresa_page(request: Request):
    return serve_page(
        request=request,
        filename="criar-empresa.html",
        require_auth=False,
        redirect_if_logged="/app",
    )


@app.get("/app", include_in_schema=False)
@app.get("/app.html", include_in_schema=False)
def app_page(request: Request):
    return serve_page(
        request=request,
        filename="app.html",
        require_auth=True,
    )


@app.get("/dominios", include_in_schema=False)
@app.get("/dominios.html", include_in_schema=False)
def dominios_page(request: Request):
    return serve_page(
        request=request,
        filename="dominios.html",
        require_auth=True,
    )


@app.get("/caixas-email", include_in_schema=False)
@app.get("/caixas-email.html", include_in_schema=False)
def caixas_email_page(request: Request):
    return serve_page(
        request=request,
        filename="caixas-email.html",
        require_auth=True,
    )


@app.get("/mail", include_in_schema=False)
@app.get("/mail.html", include_in_schema=False)
def mail_page(request: Request):
    return serve_page(
        request=request,
        filename="mail.html",
        require_auth=True,
    )


@app.get("/configuracoes", include_in_schema=False)
@app.get("/configuracoes.html", include_in_schema=False)
def configuracoes_page(request: Request):
    return serve_page(
        request=request,
        filename="configuracoes.html",
        require_auth=True,
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    favicon_path = ASSETS_DIR / "img" / "fav-icon.png"
    if favicon_path.exists():
        return FileResponse(favicon_path, media_type="image/png")
    return RedirectResponse(url="/assets/img/fav-icon.png")