"""
Arranque fail-fast: `ensure_indices` y sus reintentos acotados.

Incidente del 2026-08-28: credenciales de Atlas inválidas → ensure_indices
falló, el error se tragó con un WARNING y el backend "arrancó" sin el índice
único de `users.email`, admitiendo datos corruptos en silencio. Aquí se fija
que eso ya no puede pasar:

- camino feliz: los índices se crean sobre mongomock sin error (regresión);
- camino de fallo: si `create_index` lanza, `ensure_indices` PROPAGA;
- wrapper de arranque: reintenta un número acotado de veces y, agotados los
  intentos, falla el arranque.

El camino de fallo se recorre con `attempts`/`backoff_seconds`/`sleep`
inyectados, así que NO hay esperas reales (el `sleep` falso solo apunta las
llamadas).

In-process (mongomock vía conftest).
"""
import asyncio

import pytest


@pytest.fixture(scope="module")
def srv():
    import server
    return server


class Boom(Exception):
    """Fallo simulado de Mongo al crear un índice (p. ej. credenciales malas)."""


# --- Camino feliz (regresión) ---------------------------------------------

def test_ensure_indices_ok_on_mongomock(srv):
    """Los índices se crean sin error. Con el fail-fast activo, que esto pase
    demuestra además que no había ningún fallo latente que el WARNING ocultara."""
    asyncio.run(srv.ensure_indices())


def test_users_email_unique_index_is_declared(srv):
    """El índice crítico del incidente (único de email) se declara de verdad."""
    async def _run():
        await srv.ensure_indices()
        return await srv.db.users.index_information()

    info = asyncio.run(_run())
    assert any(spec.get("unique") for spec in info.values()), info


# --- Camino de fallo: ensure_indices propaga ------------------------------

class _FailingCollection:
    """Colección cuyo create_index siempre falla (simula Atlas inalcanzable)."""

    async def create_index(self, *a, **kw):
        raise Boom("credenciales inválidas")

    async def drop_index(self, *a, **kw):
        raise Boom("credenciales inválidas")


class _FailingDB:
    """Stand-in de `db`. Se sustituye la BASE entera, no una colección suelta:
    `db.users` construye un objeto de colección NUEVO en cada acceso, así que
    parchear una instancia no afectaría a la que usa ensure_indices."""

    def __getattr__(self, name):
        return _FailingCollection()


def test_ensure_indices_propagates_failure(srv, monkeypatch):
    """Si crear un índice falla, ensure_indices NO se lo traga: re-lanza."""
    monkeypatch.setattr(srv, "db", _FailingDB())
    with pytest.raises(Boom):
        asyncio.run(srv.ensure_indices())


# --- Wrapper de arranque: reintentos acotados -----------------------------

def test_retry_gives_up_and_raises(srv, monkeypatch):
    """Agotados los intentos, el arranque falla (RuntimeError) y NO entra en
    bucle infinito: exactamente `attempts` llamadas y `attempts - 1` esperas."""
    calls = {"n": 0}
    slept = []

    async def _boom(*a, **kw):
        calls["n"] += 1
        raise Boom("Atlas caído")

    async def _fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(srv, "ensure_indices", _boom)

    with pytest.raises(RuntimeError):
        asyncio.run(
            srv.ensure_indices_with_retry(attempts=3, backoff_seconds=0.01, sleep=_fake_sleep)
        )

    assert calls["n"] == 3, calls
    assert slept == [0.01, 0.01], slept  # espera entre intentos, no tras el último


def test_retry_recovers_on_second_attempt(srv, monkeypatch):
    """Un fallo transitorio no debe tumbar el arranque: si el 2º intento va
    bien, el wrapper vuelve sin lanzar."""
    calls = {"n": 0}

    async def _flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Boom("timeout transitorio")

    async def _fake_sleep(seconds):
        pass

    monkeypatch.setattr(srv, "ensure_indices", _flaky)
    asyncio.run(
        srv.ensure_indices_with_retry(attempts=3, backoff_seconds=0.01, sleep=_fake_sleep)
    )
    assert calls["n"] == 2, calls


def test_retry_does_not_sleep_when_first_attempt_succeeds(srv, monkeypatch):
    """Camino feliz: una sola llamada y ninguna espera."""
    calls = {"n": 0}
    slept = []

    async def _ok(*a, **kw):
        calls["n"] += 1

    async def _fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(srv, "ensure_indices", _ok)
    asyncio.run(
        srv.ensure_indices_with_retry(attempts=3, backoff_seconds=99, sleep=_fake_sleep)
    )
    assert calls["n"] == 1 and slept == []


def test_startup_handler_fails_when_indices_cannot_be_created(srv, monkeypatch):
    """El handler de arranque propaga: uvicorn no levanta el servicio roto."""
    async def _boom(*a, **kw):
        raise Boom("sin conexión")

    monkeypatch.setattr(srv, "ensure_indices", _boom)
    monkeypatch.setattr(srv, "STARTUP_INDEX_ATTEMPTS", 2)
    monkeypatch.setattr(srv, "STARTUP_INDEX_BACKOFF_SECONDS", 0)

    with pytest.raises(RuntimeError):
        asyncio.run(srv.startup_ensure_indices())
