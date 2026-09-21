"""Single-worker bounded development service entrypoint; never starts main.py."""
import logging
import os
import uvicorn

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
if __name__ == "__main__":
    uvicorn.run("ragflow_dev.app:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")),
                # Uvicorn counts idle proxy connections too; this is not the
                # model concurrency (native work remains serialized by Runtime).
                workers=1, access_log=False, log_level="warning", limit_concurrency=64,
                timeout_keep_alive=2)
