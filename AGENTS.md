# AGENTS.md

Notes for AI coding agents that write code with this SDK, or work in this repository.

## Not python-ovh

- This is not python-ovh (`pip install ovh`, `import ovh`). Do not mix them. Here:
  `pip install ovhcloud`, `import ovhcloud`.
- Credentials are an OAuth2 service account (`OVH_CLIENT_ID`, `OVH_CLIENT_SECRET`,
  `OVH_REGION`). No application key, consumer key or `ovh.conf`.
- Paths take their version: python-ovh's `client.get("/me")` is `client.get("/v1/me")`, and
  better `client.me.get_account_details()`. A raw body is one dict, not keyword arguments.

## Find the right method

- Each API section is a client attribute, in snake_case: `client.me`,
  `client.public_cloud` (the `publicCloud` API). Its types are in its `models` module:
  `from ovhcloud.api.public_cloud import models`.
- To find the method of a route, read `index/<section>.jsonl`. It has one JSON line per
  method, with the route, the Python signature, the summary, the IAM actions (`iam`), and the
  module to import. It is at the root of this repository, and in the installed package
  (`ovhcloud/index/`, next to this file and `llms.txt`). Search it before you guess a name. From a project that uses the SDK, this searches the version it
  uses:

  ```shell
  grep -h '"path":"/v1/me"' \
      "$(python -c 'import ovhcloud, os; print(os.path.dirname(ovhcloud.__file__))')"/index/*.jsonl
  ```

- To tell the user what to grant the service account, list the `iam` of the methods your
  program calls, from the index or from the docstrings.
- The docstring of each method starts with its route:
  `get_account_details calls GET /v1/me`. It then gives the API's description, the
  arguments, the IAM actions the call needs, and whether it is deprecated. A deprecated method
  names its replacement route when the API gives one: look it up in the index too. `all_x`
  iterators say which list they walk, its arguments, and the IAM actions of both calls. A
  deprecated model field says `Deprecated` in its docstring.
- `help(ovhcloud.api.<section>)` gives the section's size, its route prefixes, the list
  methods to start from, and its index file.
- Routes start with their API version, `/v1/` or `/v2/`. The same path can exist in both.
- At run time, `ovhcloud.lookup_operation("me.get_account_details")` returns an operation's
  route, summary and IAM actions, `ovhcloud.match_operation("GET", "/v1/me/sshKey/my-key")`
  finds the operation of a concrete path, and `ovhcloud.operations()` lists them all.

## Write the call

- One client for the whole program: `client = ovhcloud.Client()`. It reads `OVH_CLIENT_ID`,
  `OVH_CLIENT_SECRET` and `OVH_REGION` (`eu`, `ca` or `us`). It is safe to share between
  threads. Use it in a `with` block, or call `client.close()`.
- In an asyncio program, use `ovhcloud.AsyncClient()` instead: the same arguments and
  methods, with `await`. Iterators are async (`async for`). Wait with
  `await ovhcloud.async_wait_ready(...)` and the other `async_` forms.
- Arguments come in this order: path parameters, required query parameters, the request
  body. Optional parameters are keyword-only, after them. Leave out what you do not set.
- Names are snake_case: methods (`get_ssh_key`), arguments (`key_name`), fields
  (`ip_address`). Classes keep the API's acronyms upper case: `DedicatedServerIPBlock`. Enum
  members are UPPER_CASE: `WidgetStateEnum.OK`. Check the `models` module before you use one.
- A request body is a model of the section: `models.WidgetWidgetWritable(name="x")`. Only the
  fields you set are sent. A field set to `None` is sent as `null`. A dict body is turned into
  the model first: a dict that does not match raises `ovhcloud.InvalidRequestError`.
- A `datetime` you send needs a time zone: `datetime.datetime.now(datetime.UTC)`. A naive one raises
  `ovhcloud.InvalidRequestError`.
- A request body has no read-only field. A body whose type has some takes `<Type>Writable`
  instead (`get_env_var` returns `HostingWebEnvVarAlt`, `update_env_var` takes
  `HostingWebEnvVarWritable`). To change an object: get it, call `obj.writable()`, change the
  fields you need, send it. A field marked `Read-only` in a returned type is set by the API.
- Enums are open. A value the SDK does not know is still accepted, as a new member. A string
  works where a method takes an enum, and in an enum field of a `<Type>Writable` or of an
  inline request body: `WidgetWidgetWritable(name="web", state="ok")`. Elsewhere, pyright wants the
  member: in a list of enums (`[WidgetStateEnum.OK]`), and in a body type that is also a
  response type (no `Writable` form). At run time a string works everywhere.
- To log or return a result, use `obj.to_dict()` or `obj.to_json()`: API names, only the
  fields the API sent. Not `model_dump()`: it gives snake_case names and `None` for every
  field that was not sent.
- A response that does not match its schema is still returned. Then a required field
  (`id: str`) can be `None`. `ovhcloud.is_validated(obj)` is `False` for such an object.
- `list_x` returns a list, often of IDs only. `all_x` is an iterator over the objects: a `for`
  loop gets them one at a time. An error stops the loop with an exception.
- Paginated v2 lists have only `all_x`. There is no method that loads every page at once:
  use `list(client.<section>.all_<x>(...))` if you need them all.
- A path parameter must not be empty: the call fails before it sends anything, with
  `ovhcloud.InvalidRequestError`.
- No method for a route yet? Call it directly: `client.get("/v1/me")`,
  `client.post("/v1/...", {"key": "value"})`. It returns plain dicts and lists, or the type you
  pass as `result=`: `client.get("/v1/me/sshKey", result=list[str])`. Build a path with
  parameters with `ovhcloud.path("/v1/me/sshKey/{keyName}", keyName=name)`: it escapes them.
- A path starts with `/v1/` or `/v2/`. python-ovh's `/1.0/me` is `/v1/me` here. A path
  without its version raises `ovhcloud.InvalidRequestError`, with the path to use.

## Wait for the work to finish

- Many calls only start the work. A v2 resource comes back `CREATING` or `UPDATING`. A v1
  call often returns a task. Do not sleep in a loop: wait with the GET of the same object.
- `ovhcloud.wait_ready(get)` polls until `resource_status` is `READY`.
  `ovhcloud.wait_task(get)` polls until a task's `status` is `done`. `ovhcloud.wait_gone(get)`
  polls until a 404, after a delete. `get` is a function with no argument that calls the
  generated GET:

  ```python
  instance = ovhcloud.wait_ready(lambda: client.public_cloud.get_instance(project_id, instance_id))
  ```

- A failed status (`ERROR`, a task in error or waiting for an action) raises
  `ovhcloud.WaitFailedError`. The wait gives up after 30 minutes with
  `ovhcloud.WaitTimeoutError`: `timeout=` changes that. `ovhcloud.wait(get, done)` takes any
  condition.

## Handle errors

- Every exception of the SDK is an `ovhcloud.OvhError`. An error status from the API is an
  `ovhcloud.ApiError`. Its message is the API's own.
- Catch a common status by its class: `NotFoundError`, `ForbiddenError`, `UnauthorizedError`,
  `BadRequestError`, `ConflictError`, `TooManyRequestsError`.
- Read `status_code`, `error_class`, `message`, `query_id` (for support) and `operation`, the
  method's name, on any `ApiError`.
- A 403 means the service account lacks an IAM action. The message ends with the actions the
  call needs (`requires the IAM action account:apiovh:me/get`), also in `iam_actions`: report them
  to the user, who can grant them. Retrying does not help.
- A request the client is configured to refuse raises `ovhcloud.NotAllowedError`, and nothing
  is sent. Do not work around it: ask the user.
- With `dry_run=True`, a call that would change something raises `ovhcloud.DryRunError`. It is
  not a failure: it tells what would have been sent.
- A timeout raises `ovhcloud.RequestTimeoutError`. It is a `TransportError` and a
  `TimeoutError`. It is never retried: the server may have done the work.

## Configure the client

- To explore an account safely, use a read-only client: `ovhcloud.Client(read_only=True)`
  sends only `GET` and `HEAD`. `read_only=["cloud.reboot_project_instance"]` also allows that one
  operation. `allowed_operations=["me.*", "*.get_*"]` sends only the operations whose name
  matches. A request must pass both when both are set.
- To plan a change before making it, use `ovhcloud.Client(dry_run=True)`. Reads are sent, so
  you see the real state. Any other call is not sent: it raises `ovhcloud.DryRunError` with
  the `method`, the full `url`, the `headers` and the JSON `body` it would have sent. Show
  these to the user, then make the change with a normal client once they agree.
- To log or veto calls, use `before_request=hook` (raise an exception to stop the call: the
  caller gets `ovhcloud.HookRefusedError`) and `after_request=hook` (sees every call, with
  its `status_code`, `query_id`, `error`, `duration` and `attempts`). The hooks get a
  `CallInfo` with the operation, so `call.operation.name` and `call.operation.read_only` tell
  what the call does. Each page of an `all_x` iterator is a separate call. Calls made at the
  same time run a hook at the same time, so a hook must be safe for that.
- There is no timeout by default. Set one: `ovhcloud.Client(timeout=30)`.
- Retries are off by default. `retry=True` retries only `GET`, `HEAD` and `DELETE`, never
  `POST`, `PUT` or `PATCH`: those can start tasks or place orders. In tests, pass
  `retry_sleep=lambda s: None` so a mocked `503` does not really wait.
- `debug=True` logs requests on the `ovhcloud` logger, with credentials hidden.
  `debug_bodies=True` also logs bodies, which can hold secrets.
- For tracing, metrics or the `X-Ovh-Queryid` of a call that succeeds, pass your own
  `http_client=httpx.Client(event_hooks=...)`, or use the OpenTelemetry httpx instrumentation.
  Set `timeout=` then: httpx's own default is 5 seconds.

## Test code that uses the SDK

- No network and no credentials: `ovhcloud.Client(token_source=ovhcloud.StaticTokenSource("t"))`,
  and mock the API with respx (`respx.mock(base_url="https://api.eu.ovhcloud.com")`) or
  `http_client=httpx.Client(transport=httpx.MockTransport(handler))`. Mock paths with their
  version: `/v1/me`. The host is the region's: `api.ca.ovhcloud.com` for `region="ca"`.
- With `retry=`, pass `retry_sleep=lambda s: None` (an `async` function for `AsyncClient`).
- Answer with JSON, and an error status for an error: a 404 makes the call raise
  `ovhcloud.NotFoundError`.
- A fake return value is a model built with its required fields and the fields your code
  reads: `models.WidgetWidget(id="w-1", name="web")`.
- One `AsyncClient` per event loop: create it in the test or a fixture of the same loop
  scope, never at module level.

## Change this repository

- `src/ovhcloud/api/`, `index/` and `llms.txt` are generated at each release. Do not edit
  them: the next release overwrites the change. Report the problem instead, with the route.
- `src/ovhcloud/_core/` is hand-written. Each export replaces this whole repository, so a
  change made here is ported by the maintainers into the generator: see
  [CONTRIBUTING.md](CONTRIBUTING.md).
- Check a change with `uvx ruff check src` and
  `uvx pyright --pythonpath .venv/bin/python src/ovhcloud/_core`. The SDK's tests are not part
  of this repository.
- [examples/](examples/README.md) has small programs that call real methods. It is in the
  repository and the sdist, not in the installed package.

More: [README.md](README.md) is the full guide.
