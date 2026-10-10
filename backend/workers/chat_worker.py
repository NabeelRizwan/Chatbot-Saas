import os
from importlib import import_module


def warm_runtime():
    """Load the selected chat path before Hatchet can dispatch requests."""
    from services.knowledge_runtime import engine_name

    import_module("services.rag_service")
    if engine_name() == "llamaindex":
        import_module("services.llama_rag.answer")
        from services.structural_chunking import local_tokenizer
        local_tokenizer()
    else:
        import_module("services.native_rag.answer")


def main():
    from services.chat_execution import get_broker, is_enabled
    from services.chat_execution.workflow import build_task

    if not is_enabled():
        raise RuntimeError("Set CHAT_EXECUTION_MODE=hatchet to start the optional chat worker")
    warm_runtime()
    broker = get_broker()
    worker = broker.hatchet.worker(
        os.getenv("CHAT_EXECUTION_WORKER_NAME", "saas-chat-worker"),
        slots=int(os.getenv("CHAT_EXECUTION_WORKER_SLOTS", "20")),
        workflows=[build_task(broker.hatchet)],
    )
    try:
        worker.start()
    finally:
        from services.llama_rag.client_runtime import close_retrieval_clients
        close_retrieval_clients()
        broker.close()


if __name__ == "__main__":
    main()
