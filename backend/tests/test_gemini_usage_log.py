"""
Logging de consumo de tokens de Gemini (_log_gemini_usage).

Solo logging (sin persistir). Verifica que:
- con usage_metadata emite una línea INFO etiquetada por operación con in/out/total,
- sin usage_metadata (None) no rompe y marca tokens=unavailable,
- un usage_metadata que lanza al leerse no propaga la excepción.

No llama a Gemini real: se le pasa un objeto response falso.
"""
import logging

import pytest


@pytest.fixture(scope="module")
def srv():
    import server
    return server


class _UM:
    prompt_token_count = 48213
    candidates_token_count = 1204
    total_token_count = 49417


class _Resp:
    usage_metadata = _UM()


class _RespNoUsage:
    usage_metadata = None


class _Boom:
    @property
    def usage_metadata(self):
        raise RuntimeError("kaboom")


def test_logs_tokens_when_available(srv, caplog):
    with caplog.at_level(logging.INFO):
        srv._log_gemini_usage("generate_questions", _Resp())
    line = next(r.getMessage() for r in caplog.records if "GEMINI-USAGE" in r.getMessage())
    assert "op=generate_questions" in line
    assert "in=48213" in line and "out=1204" in line and "total=49417" in line


def test_unavailable_metadata_does_not_break(srv, caplog):
    with caplog.at_level(logging.INFO):
        srv._log_gemini_usage("summary", _RespNoUsage())
    assert any("tokens=unavailable" in r.getMessage() and "op=summary" in r.getMessage()
               for r in caplog.records)


def test_metadata_access_error_is_swallowed(srv):
    # No debe propagar: el logging nunca puede tumbar la petición.
    srv._log_gemini_usage("eval_dev", _Boom())
