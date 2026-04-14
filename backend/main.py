from pathlib import Path
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.routers.auth import is_authenticated
from backend.routers.caixas_email import router as caixas_email_router
from backend.routers.criar_empresa import router as criar_empresa_router
from backend.routers.dominios import router as dominios_router
from backend.routers.login import router as login_router
from backend.routers.webmail import (
    router as webmail_router,
    start_scheduled_sender,
    stop_scheduled_sender,
)
from backend.routers.webmail_auth import (
    is_webmail_authenticated,
    router as webmail_auth_router,
)

print("MAIN FILE:", __file__)
print("WEBMAIL ROUTER IMPORTADO DE:", getattr(webmail_router, "__module__", None))

LOG_LEVEL = (os.getenv("AUREMAIL_LOG_LEVEL", "WARNING") or "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.WARNING),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("auremail").setLevel(getattr(logging, LOG_LEVEL, logging.WARNING))

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"

app = FastAPI(
    title="AureMail",
    version="0.1.1",
)

# Não criar/alterar tabela no boot do app.
# Banco deve ser tratado por migration/script separado.

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

app.include_router(login_router)
app.include_router(webmail_auth_router)
app.include_router(criar_empresa_router)
app.include_router(dominios_router)
app.include_router(webmail_router)
app.include_router(caixas_email_router)


@app.on_event("startup")
def startup_debug_routes():
    print("STARTUP MAIN FILE:", __file__)
    print("STARTUP WEBMAIL MODULE:", getattr(webmail_router, "__module__", None))
    print("STARTUP ROUTES BEGIN")
    for route in app.routes:
        try:
            methods = ",".join(sorted(route.methods or []))
            print(f"ROTA: {methods} {route.path}")
        except Exception as exc:
            print("ROTA ERROR:", exc)
    print("STARTUP ROUTES END")
    start_scheduled_sender()


@app.on_event("shutdown")
def shutdown_background_workers():
    stop_scheduled_sender()


def frontend_file(filename: str) -> Path:
    return FRONTEND_DIR / filename


def has_panel_access(request: Request) -> bool:
    return is_authenticated(request)


def has_webmail_access(request: Request) -> bool:
    return is_webmail_authenticated(request)


def has_mail_access(request: Request) -> bool:
    return has_panel_access(request) or has_webmail_access(request)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=302)


def serve_page(
    request: Request,
    filename: str,
    require_panel_auth: bool = False,
    require_mail_auth: bool = False,
    redirect_if_panel_logged: str | None = None,
    redirect_if_mail_logged: str | None = None,
):
    if require_panel_auth and not has_panel_access(request):
        return redirect("/login")

    if require_mail_auth and not has_mail_access(request):
        return redirect("/webmail-login")

    if redirect_if_panel_logged and has_panel_access(request):
        return redirect(redirect_if_panel_logged)

    if redirect_if_mail_logged and has_mail_access(request):
        return redirect(redirect_if_mail_logged)

    file_path = frontend_file(filename)
    if not file_path.exists() or not file_path.is_file():
        return redirect("/login")

    return FileResponse(file_path)


@app.get("/", include_in_schema=False)
def root(request: Request):
    if has_panel_access(request):
        return redirect("/app")

    if has_webmail_access(request):
        return redirect("/mail")

    return redirect("/login")


@app.get("/login", include_in_schema=False)
@app.get("/login.html", include_in_schema=False)
def login_page(request: Request):
    return serve_page(
        request=request,
        filename="login.html",
        redirect_if_panel_logged="/app",
        redirect_if_mail_logged="/mail",
    )


@app.get("/webmail-login", include_in_schema=False)
@app.get("/webmail-login.html", include_in_schema=False)
def webmail_login_page(request: Request):
    return serve_page(
        request=request,
        filename="webmail-login.html",
        redirect_if_mail_logged="/mail",
        redirect_if_panel_logged="/app",
    )


@app.get("/criar-empresa", include_in_schema=False)
@app.get("/criar-empresa.html", include_in_schema=False)
def criar_empresa_page(request: Request):
    return serve_page(
        request=request,
        filename="criar-empresa.html",
        redirect_if_panel_logged="/app",
        redirect_if_mail_logged="/mail",
    )


@app.get("/app", include_in_schema=False)
@app.get("/app.html", include_in_schema=False)
def app_page(request: Request):
    return serve_page(
        request=request,
        filename="app.html",
        require_panel_auth=True,
    )


@app.get("/dominios", include_in_schema=False)
@app.get("/dominios.html", include_in_schema=False)
def dominios_page(request: Request):
    return serve_page(
        request=request,
        filename="dominios.html",
        require_panel_auth=True,
    )


@app.get("/caixas-email", include_in_schema=False)
@app.get("/caixas-email.html", include_in_schema=False)
def caixas_email_page(request: Request):
    return serve_page(
        request=request,
        filename="caixas-email.html",
        require_panel_auth=True,
    )


@app.get("/configuracoes", include_in_schema=False)
@app.get("/configuracoes.html", include_in_schema=False)
def configuracoes_page(request: Request):
    return serve_page(
        request=request,
        filename="configuracoes.html",
        require_panel_auth=True,
    )


@app.get("/mail", include_in_schema=False)
@app.get("/mail.html", include_in_schema=False)
def mail_page(request: Request):
    return serve_page(
        request=request,
        filename="mail.html",
        require_mail_auth=True,
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    candidates = [
        ASSETS_DIR / "img" / "favicon.ico",
        ASSETS_DIR / "favicon.ico",
        ASSETS_DIR / "img" / "logo.png",
    ]

    for file_path in candidates:
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)

    return RedirectResponse(url="/login", status_code=302)