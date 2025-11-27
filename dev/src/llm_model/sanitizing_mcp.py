# sanitizing_mcp.py
from copy import deepcopy
import asyncio, json, inspect

def _as_list(x):
    if x is None: return []
    return x if isinstance(x, list) else [x]

def _apply_defaults(obj, schema):
    props = schema.get("properties", {})
    for k, spec in props.items():
        if k not in obj and "default" in spec:
            obj[k] = deepcopy(spec["default"])
        if k in obj:
            v = obj[k]
            if isinstance(v, dict) and "object" in _as_list(spec.get("type")):
                _apply_defaults(v, spec)
            elif isinstance(v, list) and "array" in _as_list(spec.get("type")):
                item_schema = spec.get("items", {})
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        _apply_defaults(item, item_schema)

def _sanitize_by_schema(obj, schema):
    props = schema.get("properties", {})
    for k, spec in props.items():
        if k not in obj: continue
        v = obj[k]
        types = _as_list(spec.get("type"))

        if isinstance(v, str) and v.strip() == "" and "string" not in types:
            if "null" in types:
                obj[k] = None
            else:
                obj.pop(k, None)
            continue

        if isinstance(v, dict) and "object" in types:
            _sanitize_by_schema(v, spec)
        elif isinstance(v, list) and "array" in types:
            item_schema = spec.get("items", {})
            item_types = _as_list(item_schema.get("type"))
            new_items = []
            for it in v:
                if isinstance(it, str) and it.strip() == "" and "string" not in item_types:
                    continue
                if isinstance(it, dict):
                    _sanitize_by_schema(it, item_schema)
                new_items.append(it)
            obj[k] = new_items

def _soft_normalize(args, schema):
    args = deepcopy(args or {})
    _sanitize_by_schema(args, schema)
    _apply_defaults(args, schema)
    return args

def _loosen_common_schema_edges(schema):
    schema = deepcopy(schema or {"type": "object", "properties": {}})
    props = schema.setdefault("properties", {})
    # Friendlier 'path'
    if "path" in props:
        spec = props["path"]
        t = _as_list(spec.get("type")) or ["object"]
        if "object" not in t: t.append("object")
        if "null" not in t: t.append("null")
        spec["type"] = t
        spec.setdefault("default", {})
        if "required" in schema and isinstance(schema["required"], list):
            schema["required"] = [k for k in schema["required"] if k != "path"]
    return schema

async def _maybe_await(v):
    if asyncio.iscoroutine(v): return await v
    return v

def _getattr_or_key(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

def _setattr_or_key(obj, key, value):
    if isinstance(obj, dict):
        obj[key] = value
    else:
        try:
            setattr(obj, key, value)
        except Exception:
            # last resort: if object is frozen, do nothing (we’ll cache schema anyway)
            pass

class SanitizingMCP:
    """
    Keeps original tool objects intact.
    - list_tools/tools: relax schema on each tool object (no type change) and cache per name.
    - call_tool/callTool: extract (name, arguments), normalize by cached schema, delegate.
    """
    def __init__(self, inner):
        self._inner = inner
        self._tool_schemas = {}  # name -> adjusted schema

    # ---------- context ----------
    async def __aenter__(self):
        if hasattr(self._inner, "__aenter__"):
            await _maybe_await(self._inner.__aenter__())
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if hasattr(self._inner, "__aexit__"):
            return await _maybe_await(self._inner.__aexit__(exc_type, exc, tb))
        return False

    # ---------- tool discovery ----------
    async def list_tools(self, *args, **kwargs):
        getter = None
        if hasattr(self._inner, "list_tools"):
            getter = getattr(self._inner, "list_tools")
        elif hasattr(self._inner, "tools"):
            getter = getattr(self._inner, "tools")
        else:
            return []

        tools = await _maybe_await(getter(*args, **kwargs)) or []
        for t in tools:
            name = _getattr_or_key(t, "name")
            # input schema may live under 'inputSchema' or 'parameters'
            schema = _getattr_or_key(t, "inputSchema") or _getattr_or_key(t, "parameters") or {"type":"object","properties":{}}
            schema = _loosen_common_schema_edges(schema)
            # write back without changing type
            if _getattr_or_key(t, "inputSchema") is not None or not _getattr_or_key(t, "parameters"):
                _setattr_or_key(t, "inputSchema", schema)
            else:
                _setattr_or_key(t, "parameters", schema)
            if name:
                self._tool_schemas[name] = schema
        return tools

    async def tools(self, *args, **kwargs):
        return await self.list_tools(*args, **kwargs)

    # ---------- tool execution ----------
    async def call_tool(self, *args, **kwargs):
        # Try to extract name/arguments regardless of signature
        name = kwargs.get("name")
        arguments = kwargs.get("arguments")

        req_obj = None
        if name is None and args:
            req_obj = args[0]
            # Common shapes:
            # - (name, arguments, ...)
            # - ({'name':..., 'arguments':...}, ...)
            # - (RequestObj(name=..., arguments=...), ...)
            if isinstance(req_obj, str) and len(args) >= 2:
                name, arguments = args[0], args[1]
            else:
                cand_name = _getattr_or_key(req_obj, "name")
                cand_args = _getattr_or_key(req_obj, "arguments")
                if cand_name is not None:
                    name, arguments = cand_name, cand_args

        # Parse JSON string if needed
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except Exception:
                arguments = {}

        schema = self._tool_schemas.get(name) or {"type":"object","properties":{}}
        norm = _soft_normalize(arguments, schema)

        # Delegate to inner, preferring kwargs if supported
        inner_call = getattr(self._inner, "call_tool", None) or getattr(self._inner, "callTool", None)
        if inner_call is None:
            inner_call = getattr(self._inner, "call", None)
        if inner_call is None:
            raise AttributeError("Inner MCP server lacks call_tool/callTool/call")

        # Try calling with kwargs (name=..., arguments=...)
        try:
            return await _maybe_await(inner_call(name=name, arguments=norm))
        except TypeError:
            pass

        # Fallbacks:
        # 1) If original looked like (name, arguments, *rest), rebuild positional
        if isinstance(req_obj, str) and len(args) >= 2:
            new_args = (name, norm, *args[2:])
            return await _maybe_await(inner_call(*new_args, **kwargs))

        # 2) If original looked like (RequestObj, *rest), try to mutate its 'arguments'
        if req_obj is not None:
            try:
                if isinstance(req_obj, dict):
                    req_obj["arguments"] = norm
                else:
                    setattr(req_obj, "arguments", norm)
                new_args = (req_obj, *args[1:])
                return await _maybe_await(inner_call(*new_args, **kwargs))
            except Exception:
                pass

        # 3) Last resort: pack a request dict
        return await _maybe_await(inner_call({"name": name, "arguments": norm}))
    
    async def callTool(self, *args, **kwargs):
        return await self.call_tool(*args, **kwargs)

    # ---------- passthrough ----------
    def __getattr__(self, item):
        return getattr(self._inner, item)
