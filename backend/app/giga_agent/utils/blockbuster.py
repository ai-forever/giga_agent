def _enable_blockbuster():
    _patch_blocking_error()
    from blockbuster import BlockBuster

    bb = BlockBuster(excluded_modules=[])

    bb.functions["os.path.abspath"].can_block_in("inspect.py", "getmodule")
    for fn in (
        "os.access",
        "os.getcwd",
        "os.unlink",
        "os.write",
    ):
        bb.functions[fn].can_block_in(
            "langgraph_api/api/profile.py", "_profile_with_pyspy"
        )

    for module, func in (
        ("memory/__init__.py", "sync"),
        ("memory/__init__.py", "load"),
        ("memory/__init__.py", "dump"),
        ("pydantic/main.py", "__init__"),
    ):
        bb.functions["os.remove"].can_block_in(module, func)
        bb.functions["os.rename"].can_block_in(module, func)
    # bb.functions["os.mkdir"].can_block_in(
    #     "qdrant_client/local/async_qdrant_local.py", "create_collection"
    # )

    for module, func in (
        ("uvicorn/lifespan/on.py", "startup"),
        ("uvicorn/lifespan/on.py", "shutdown"),
        ("ansitowin32.py", "write_plain_text"),
        ("logging/__init__.py", "flush"),
        ("logging/__init__.py", "emit"),
    ):
        bb.functions["io.TextIOWrapper.write"].can_block_in(module, func)
        bb.functions["io.BufferedWriter.write"].can_block_in(module, func)
    # Support pdb
    bb.functions["builtins.input"].can_block_in("bdb.py", "trace_dispatch")
    bb.functions["builtins.input"].can_block_in("pdb.py", "user_line")
    to_disable = [
        # Some libs create small cache/state directories at import/startup time
        # (e.g. `.langgraph_api/`). These should not crash dev server.
        "os.mkdir",
        "os.stat",
        # This is used by tiktoken for get_encoding_for_model
        # as well as importlib.metadata.
        "os.listdir",
        "os.remove",
        # We used to block the IO things but people use them so often that
        # we've decided to just let people make bad decisions for themselves.
        "io.BufferedReader.read",
        "io.BufferedWriter.write",
        "io.TextIOWrapper.read",
        "io.TextIOWrapper.write",
        # If people are using threadpoolexecutor, etc. they'd be using this.
        "threading.Lock.acquire",
    ]

    for function in bb.functions:
        if function.startswith("os.path."):
            to_disable.append(function)
    for function in to_disable:
        func = bb.functions.pop(function, None)
        if func:
            func.deactivate()
    bb.activate()

    return bb


def _patch_blocking_error():
    from blockbuster.blockbuster import BlockingError

    original = BlockingError.__init__

    def init(self, func: str, *args, **kwargs):
        msg_ = func + (
            "\n\n"
            "Heads up! LangGraph dev identified a synchronous blocking call in your code. "
            "When running in an ASGI web server, blocking calls can degrade performance for everyone since they tie up the event loop.\n\n"
            "Here are your options to fix this:\n\n"
            "1. Best approach: Convert any blocking code to use async/await patterns\n"
            "   For example, use 'await aiohttp.get()' instead of 'requests.get()'\n\n"
            "2. Quick fix: Move blocking operations to a separate thread\n"
            "   Example: 'await asyncio.to_thread(your_blocking_function)'\n\n"
            "3. Override (if you can't change the code):\n"
            "   - For development: Run 'langgraph dev --allow-blocking'\n"
            "   - For deployment: Set 'BG_JOB_ISOLATED_LOOPS=true' environment variable\n\n"
            "These blocking operations can prevent health checks and slow down other runs in your deployment. "
            "Following these recommendations will help keep your LangGraph application running smoothly!"
        )
        original(self, msg_, *args, **kwargs)

    BlockingError.__init__ = init
