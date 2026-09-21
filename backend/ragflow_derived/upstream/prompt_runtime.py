# Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# http://www.apache.org/licenses/LICENSE-2.0
# Modified for Chatbot-SaaS: selected pure helpers, no product globals/cache setup.
import hashlib
import tiktoken


def hash_str2int(line: str, mod: int = 10**8) -> int:
    return int(hashlib.sha1(line.encode("utf-8")).hexdigest(), 16) % mod


def get_encoder():
    return tiktoken.get_encoding("cl100k_base")
