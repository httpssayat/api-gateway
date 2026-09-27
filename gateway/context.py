from contextvars import ContextVar

# ContextVar нужен, чтобы прокидывать correlation_id в логи
# без передачи его через все функции явно.
correlation_id_var: ContextVar[str] = ContextVar(
    "correlation_id",
    default="-",
)