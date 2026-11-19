# OVHcloud Python SDK

[![PyPI version](https://img.shields.io/pypi/v/ovhcloud.svg)](https://pypi.org/project/ovhcloud/)
[![Python versions](https://img.shields.io/pypi/pyversions/ovhcloud.svg)](https://pypi.org/project/ovhcloud/)

> **Early version.** This SDK is in active development, and v0.x releases can include breaking
> changes. Pin a version and read the [changelog](CHANGELOG.md) before you upgrade. We will release
> v1.0 once the SDK is stable, in the coming weeks. From v1.0, every stable release follows semantic
> versioning: a breaking change means a new major version.

The Python SDK for the [OVHcloud API](https://developers.eu.ovhcloud.com/): a typed method for
every public operation, with OAuth2 service-account authentication, retries, typed exceptions
and iterators over lists.

**Status:** maintained by OVHcloud. Most of the code under `src/ovhcloud/api/` is generated from
the API's OpenAPI specifications at each release. Read [CONTRIBUTING.md](CONTRIBUTING.md)
before you propose a change.

- [1. Install](#1-install)
- [2. Your first program](#2-your-first-program)
  - [Coming from python-ovh](#coming-from-python-ovh)
- [3. Finding the operation you need](#3-finding-the-operation-you-need)
- [4. Calling an operation](#4-calling-an-operation)
- [5. Lists and pagination](#5-lists-and-pagination)
- [6. Handling errors](#6-handling-errors)
- [7. Configuration reference](#7-configuration-reference)
- [8. Calling any endpoint](#8-calling-any-endpoint)
- [9. Async programs](#9-async-programs)
- [10. Testing your code](#10-testing-your-code)
- [11. Observability](#11-observability)
- [12. Troubleshooting](#12-troubleshooting)

---

## 1. Install

Python 3.11 or later.

```shell
pip install ovhcloud
```

Or `uv add ovhcloud`. The package is [`ovhcloud` on PyPI](https://pypi.org/project/ovhcloud/).

You also need OAuth2 credentials: the client ID and secret of a service account.

1. Create the service account in the OVHcloud Control Panel or with the API:
   [Managing OVHcloud service accounts](https://docs.ovhcloud.com/en/guides/manage-and-operate/api/manage-service-account).
   The secret is shown once: save it.
2. Give it the permissions your program needs with an IAM policy:
   [How to use IAM policies using the OVHcloud Control Panel](https://docs.ovhcloud.com/en/guides/account-and-service-management/account-information/iam-policy-ui),
   or [using the API](https://docs.ovhcloud.com/en/guides/account-and-service-management/account-information/iam-policies-api).

Keep the client ID and secret out of your source code: read them from the environment.

---

## 2. Your first program

This prints the details of your account: `GET /v1/me`. Copy it, set your credentials, run
it.

```python
import ovhcloud

with ovhcloud.Client() as client:  # reads OVH_CLIENT_ID, OVH_CLIENT_SECRET, OVH_REGION
    account = client.me.get_account_details()  # GET /v1/me
    print("account:", account.nichandle)
    print("email:  ", account.email)
    print("country:", account.country)
```

```shell
export OVH_CLIENT_ID=...  OVH_CLIENT_SECRET=...
export OVH_REGION=eu    # eu (default), ca or us
python first.py
```

More examples: [examples/](examples/README.md).

Create **one** client and share it: it is safe to use from several threads, and it reuses
connections and tokens. Each API section is an attribute of the client (`client.me`),
loaded the first time you use it.

### Choosing your region

Your account lives in one region. `OVH_REGION` (or `Client(region="ca")`) picks both the API
host and the token endpoint, which must agree: a token from one region is refused by the
others.

| Region | `ovhcloud.Region` | API |
|---|---|---|
| Europe | `Region.EU` | `https://api.eu.ovhcloud.com` |
| Canada | `Region.CA` | `https://api.ca.ovhcloud.com` |
| US | `Region.US` | `https://api.us.ovhcloud.com` |

### Coming from python-ovh

This SDK is not [python-ovh](https://github.com/ovh/python-ovh) (`pip install ovh`,
`import ovh`). It is a new package. The main differences:

- **Package:** `pip install ovhcloud`, then `import ovhcloud`.
- **Credentials:** an OAuth2 service account (`OVH_CLIENT_ID`, `OVH_CLIENT_SECRET`). There is
  no application key, application secret or consumer key, and no `ovh.conf` file. See
  [Install](#1-install) to create one.
- **Region:** `OVH_REGION=eu`, `ca` or `us`, instead of the endpoint `ovh-eu`, `ovh-ca` or
  `ovh-us`.
- **Methods:** each API call has a typed method. python-ovh's `GET /me` is
  `client.me.get_account_details()`. A body is a typed model, not keyword arguments.

| python-ovh | This SDK |
|---|---|
| `ovh.Client(endpoint="ovh-eu", application_key=..., application_secret=..., consumer_key=...)` | `ovhcloud.Client(region="eu", client_id=..., client_secret=...)` |
| `client.get("/me")` | `client.me.get_account_details()` |
| `client.get("/me/sshKey")` | `client.me.list_ssh_keys()` |
| `client.post("/me/sshKey", key="ssh-ed25519 AAAA...", keyName="laptop")` | `client.me.create_ssh_key(models.CreateSSHKeyRequest(key="ssh-ed25519 AAAA...", key_name="laptop"))`, with `from ovhcloud.api.me import models` |
| `ovh.exceptions.ResourceNotFoundError` | `ovhcloud.NotFoundError` |
| `ovh.exceptions.APIError` | `ovhcloud.ApiError` |

To find the method of a route you called with python-ovh, add `/v1` in front of the path and
look it up in the index (see [section 3](#3-finding-the-operation-you-need)).

---

## 3. Finding the operation you need

The SDK follows the OVHcloud API: about 90 **sections**, each one a client attribute and a
package under `ovhcloud.api`.

To see what the API offers, browse the
[API reference](https://developers.eu.ovhcloud.com/reference/) on the OVHcloud developer hub:
every operation, by product, with its route, parameters and responses. Its groups do not
match the SDK's sections one to one: take the route and find its method as below. The hub
writes a v1 route `/1.0/vrack`. The index writes it `/v1/vrack`.
`ovhcloud.match_operation` reads `/1.0/vrack` as `/v1/vrack`, and tries `/v1` then `/v2` for a
path with no version.

### Guess the name from the URL

Method names follow the URL path, without the section's own prefix:

| Route | Method |
|---|---|
| `GET /vrack` (a list) | `client.vrack.list_vracks` |
| `GET /vrack/{serviceName}` | `client.vrack.get_vrack` |
| `PUT /vrack/{serviceName}` | `client.vrack.update_vrack` |
| `POST /vrack/{serviceName}/cloudProject` | `client.vrack.create_cloud_project` |
| `DELETE /vrack/{serviceName}/cloudProject/{project}` | `client.vrack.delete_cloud_project` |
| `POST /vrack/{serviceName}/terminate` (an action) | `client.vrack.terminate` |

Path parameters are not in the name: they are arguments.

### Python names

Names follow PEP 8, whatever the case the API writes them in:

| API | Python |
|---|---|
| section `publicCloud` | `client.public_cloud`, `ovhcloud.api.public_cloud` |
| route `/ip/{ip}/dnsUrl` | method `get_dns_url` |
| parameter `serviceName` | argument `service_name` |
| property `ipAddress` | attribute `ip_address` |
| schema `dedicated.server.ipBlock` | class `DedicatedServerIPBlock` |
| enum value `NETWORK_ATTACK` | member `NETWORK_ATTACK` |
| a Python keyword, `class` | `class_` |

The names are the same as in the OVHcloud Go SDK, in Python's case. They are kept from release
to release: a route keeps its method name even when a new route would make another name
better.

### Look up the route in the index

The surest way. The SDK ships an operation index: one file per section,
`index/<section>.jsonl`, with one line per method. It is in this repository, and in the
installed package (`ovhcloud/index/`).

```shell
grep -h '"path":"/v1/vrack/{serviceName}"' \
    "$(python -c 'import ovhcloud, os; print(os.path.dirname(ovhcloud.__file__))')"/index/*.jsonl
```

```json
{"section":"vrack","method":"get_vrack","kind":"call","http":"GET","path":"/v1/vrack/{serviceName}","summary":"Get this object properties","signature":"get_vrack(self, service_name: str) -> models.VrackVrack","iam":["vrack:apiovh:get"],"id":"vrack.get_vrack","import":"ovhcloud.api.vrack"}
```

[index/README.md](index/README.md) describes the fields. `iam` lists the IAM actions the call
requires. To list what a program needs, collect the `iam` of the methods it calls: those are
the actions to grant its service account in its IAM policy.

### Search by URL path

Every method's docstring starts with its HTTP method and route, so searching for the route
always works, even when the name is not what you guessed:

```shell
grep -rh --include=_api.py "calls GET /v1/cloud/project/{serviceName}/instance:" \
    "$(python -c 'import ovhcloud, os; print(os.path.dirname(ovhcloud.__file__))')"/api/
```

```
"""list_project_instances calls GET /v1/cloud/project/{serviceName}/instance: Get instance
```

Routes carry their API version: `/v1/...` or `/v2/...`.

### Look up one method

Every method's docstring starts with its route, so your editor and `help()` show it:

```python
>>> help(client.vrack.get_vrack)
get_vrack(service_name: str) -> ovhcloud.api.vrack.models.VrackVrack
    get_vrack calls GET /v1/vrack/{serviceName}: Get this object properties
    ...
```

### At run time

`ovhcloud.lookup_operation("vrack.get_vrack")` gives an operation's route, summary and IAM
actions. `ovhcloud.match_operation("GET", "/v1/vrack/pn-1")` finds the operation of a concrete
path. `ovhcloud.operations()` lists them all.

---

## 4. Calling an operation

Arguments come in a fixed order: the path parameters, then any required query parameters, then
the request body. Optional parameters are keyword-only, after them. A call returns the result,
or raises an exception.

```python
from ovhcloud.api.vrack import models

v = client.vrack.get_vrack("pn-123456")

task = client.vrack.create_cloud_project(
    "pn-123456", models.CreateCloudProjectRequest(project="0123456789abcdef")
)
```

**Optional parameters** are keyword arguments. Leave them out when you need none:

```python
ids = client.vrack.list_vracks()                     # no filter
ids = client.vrack.list_vracks(iam_tags={"env": [{"operator": "EQ", "value": "prod"}]})
```

**Models** are [pydantic](https://docs.pydantic.dev/) models. Their attributes are snake_case.
Build them with the snake_case names: type checkers know only those. An optional field you do
not set is not sent. A field you set to `None` is sent as `null`:

```python
body = models.WidgetWidgetWritable(name="web")             # sends {"name": "web"}
body = models.WidgetWidgetWritable(name="web", size=None)  # sends {"name": "web", "size": null}
```

A method also takes a dict as its body, for code that is not type-checked. The SDK turns it
into the body model first, so snake_case names are sent by their API names. A dict that does
not match the model raises `InvalidRequestError`, and nothing is sent.

A `datetime` you send must have a time zone: `datetime.datetime.now(datetime.UTC)`. A naive
one, in a body or a query, raises `InvalidRequestError`. The API would read it in its own time
zone.

**Enums are open.** OVHcloud adds enum values often. A value this SDK version does not know is
still read, as a new member of the enum, and never fails your program. Where a method takes an
enum, a string works too.

In a request body, the enum fields of a `<Type>Writable`, and of the inline body of an
operation, also take a string for pyright: `WidgetWidgetWritable(name="web", state="ok")`. A known value
still becomes the member. Two cases still need the member for pyright, not a string:

- a list of enums: `[WidgetStateEnum.OK]`;
- a body type that is also a response type, so it has no `Writable` form.

At run time a string works in both cases.

**Responses never fail on their shape.** When the API sends a field the SDK does not know, it
is kept in `model_extra`. When a response does not match its schema (a missing required field,
a wrong type), the SDK still returns the object, with the values the API sent. If you send
that object back as a body, it is sent with those same values.

### Reading results

- `obj.to_dict()` gives the object as the API writes it: API names, only the fields the API
  sent, dates as strings. `obj.to_json()` gives the same as a JSON string. Use them to log a
  result or to return it from your own API.
- `print(obj)` shows only the fields the API sent, and the unknown ones.
- `obj.model_dump()` is pydantic's: snake_case names, and `None` for every field the API did
  not send.
- A required field is typed without `None`: `id: str`. When a response did not match its
  schema, that field can still be `None`. `ovhcloud.is_validated(obj)` is `False` for such
  an object. Check it before you trust the types:

```python
me = client.me.get_account_details()
if not ovhcloud.is_validated(me):
    logging.warning("unexpected response: %s", me.to_json())
print(me.to_dict())
```

### Request bodies have no read-only fields

The API sets some fields itself: an ID, a creation date, a status. A type the API returns has
them, marked `Read-only` in its documentation. A request body never has them, so you cannot
send one by mistake. A body whose type has read-only fields takes that type's **writable**
form instead, named with `Writable` after it.

To change an object, get it, then call its `writable()` method. It returns the object in that
form, nested objects included. Change what you need, then send it:

```python
env = client.hostingweb.get_env_var("example.com", "API_URL")  # HostingWebEnvVarAlt
body = env.writable()                                          # HostingWebEnvVarWritable
body.value = "https://api.example.com"
task = client.hostingweb.update_env_var("example.com", "API_URL", body)
```

`writable()` returns a deep copy: changing `body` leaves `env` as it was. It leaves out the
fields the SDK does not know (`model_extra`), and the fields the GET did not return. You can
also build the writable form yourself, with only the fields you set:
`models.HostingWebEnvVarWritable(value="https://api.example.com")`.

### Waiting for the work to finish

Many operations only start the work. A v2 resource comes back `CREATING` or `UPDATING` and
becomes `READY` later. Many v1 operations return a task that moves from `todo` to `done`.
Instead of sleeping in a loop, wait with the GET of the same object:

```python
instance = client.public_cloud.create_instance(project_id, spec)
instance = ovhcloud.wait_ready(lambda: client.public_cloud.get_instance(project_id, instance.id))
```

| Function | Polls until |
|---|---|
| `ovhcloud.wait_ready(get)` | the object's `resource_status` is `READY` (v2 resources) |
| `ovhcloud.wait_task(get)` | the task's `status` is `done` or `DONE` |
| `ovhcloud.wait_gone(get)` | `get` raises `NotFoundError`, after a deletion |
| `ovhcloud.wait(get, done)` | your `done` function returns `True` |

They poll every 2 seconds at first, then less often, up to every 30 seconds, and give up after
30 minutes with `WaitTimeoutError` (`timeout=`, `poll=(first, longest)`). A failed status (a
resource in `ERROR`, a task in error, cancelled, or waiting for an action) raises
`WaitFailedError`. A 429 or a 5xx is polled again. Any other error stops the wait. Both
exceptions carry the last value read, in `last`.

### `list_` and `all_`

Many v1 lists return identifiers only. Their `all_` twin is an iterator over the objects: it
lists the identifiers, then gets each object when your loop reaches it.

```python
ids = client.me.list_ssh_keys()            # list[str]

for key in client.me.all_ssh_keys():       # one model per step
    print(key.key_name)
```

Each object is one request, so a list of 900 items is 901 requests. `break` stops them. An
object deleted between the list and its fetch is skipped. Any other error is raised, and ends
the loop.

### Deprecated operations

The API deprecates operations before it removes them. Their docstring says so, with the
removal date and the route to use instead when the API gives them. Type checkers and editors
show them as deprecated. They still work, and never warn at run time.

---

## 5. Lists and pagination

v2 lists are paginated by cursor. Their only method is an `all_` iterator: it gets the next
page only when your loop needs it.

```python
for project in client.public_cloud.all_projects():
    print(project.name)

first_ten = list(itertools.islice(client.public_cloud.all_projects(), 10))  # import itertools
```

There is no method that loads every page at once. `list(...)` does it when you need it. A
walk stops after 200 pages, so a broken cursor cannot loop forever.

---

## 6. Handling errors

Every exception of the SDK is an `ovhcloud.OvhError`. An error status from the API raises an
`ovhcloud.ApiError`, or one of its subclasses for the common statuses:

| Status | Exception |
|---|---|
| 400 | `BadRequestError` |
| 401 | `UnauthorizedError` |
| 403 | `ForbiddenError` |
| 404 | `NotFoundError` |
| 409 | `ConflictError` |
| 429 | `TooManyRequestsError` |
| other | `ApiError` |

```python
try:
    client.vrack.get_vrack("pn-999")
except ovhcloud.NotFoundError:
    print("no such vRack")
except ovhcloud.ApiError as err:
    print(err.status_code, err.message, err.query_id)
```

The message is the API's own, with the operation and, on a 401 or 403, the IAM actions the
call needs:

```text
vrack.get_vrack: GET /v1/vrack/pn-1: 403 Forbidden: This call has not been granted (Client::Forbidden); requires the IAM action vrack:apiovh:get
```

| Exception | When |
|---|---|
| `ConfigurationError` | the client cannot be created: no credentials, an unknown region |
| `TokenError` | the token endpoint refused the credentials. The message never holds the secret. |
| `TransportError` | no response, or the body could not be read: connection refused, DNS, timeout, TLS. Never retried. |
| `RequestTimeoutError` | a `TransportError` that is a timeout. It is also a `TimeoutError`. |
| `InvalidRequestError` | refused before sending: a path without `/v1/` or `/v2/`, an empty path parameter, a `.` or `..` path segment, a header value that is not ASCII, a body that does not match its model, a `datetime` with no time zone |
| `NotAllowedError` | refused by `read_only` or `allowed_operations`. Nothing was sent. |
| `DryRunError` | not sent because the client has `dry_run=True`. It holds what would have been sent (section 7). |
| `HookRefusedError` | refused by a `before_request` hook. Nothing was sent. The hook's exception is its `__cause__`. |
| `ResponseTooLargeError` | the body is larger than `max_response_bytes` |
| `DecodeError` | a 2xx body is not JSON, a page of a list is not a list, or a body cannot be decompressed |
| `WaitFailedError`, `WaitTimeoutError` | a wait ended in a failure, or gave up |

---

## 7. Configuration reference

All arguments of `ovhcloud.Client` are keyword-only, and win over the environment.

| Argument | Default | Meaning |
|---|---|---|
| `region` | `OVH_REGION`, else `eu` | `eu`, `ca` or `us` |
| `client_id`, `client_secret` | `OVH_CLIENT_ID`, `OVH_CLIENT_SECRET` | an OAuth2 service account |
| `token_source` | | your own tokens: an object with a `token() -> str` method |
| `endpoint` | the region's API | another base URL, for a proxy or a test server. No version suffix. |
| `timeout` | none | seconds a request may take, from sending it to the end of the body. Each retry has its own. |
| `retry` | off | `True`, or a `RetryPolicy` |
| `max_response_bytes` | no limit | fail, never truncate, past this size |
| `read_only` | `False` | `True`: only `GET` and `HEAD`. A list of patterns: also these operations. |
| `allowed_operations` | all | only the operations whose name matches: `["vrack.*", "*.get_*"]` |
| `dry_run` | `False` | send reads (`GET`, `HEAD`) as usual. Do not send anything else: raise `DryRunError` with the URL and body it would have sent. |
| `before_request` | | a function, or a list of them, run before each call, to log it or to refuse it by raising an exception |
| `after_request` | | a function, or a list of them, run after each call, with its status, query ID, error, duration and number of attempts |
| `debug`, `debug_bodies` | off | log requests on the `ovhcloud` logger (see below) |
| `user_agent` | | your product, added after the SDK's: `"my-tool/1.2"` |
| `headers` | | headers sent with every request |
| `root_cas`, `root_cas_pem` | system | a private CA, as a PEM file or PEM data. Replaces the system's. |
| `client_cert`, `client_key` | | mutual TLS |
| `ssl_context` | | your own TLS settings. Certificates must be checked, TLS 1.2 at least. |
| `proxy` | `HTTPS_PROXY`, `NO_PROXY` | a proxy URL, or `None` for no proxy |
| `http_client` | | your own `httpx.Client` |
| `retry_sleep` | `time.sleep` | called with the seconds to wait between retry attempts. For tests: `lambda s: None`. `AsyncClient` takes an `async` function. |

`client.with_options(timeout=5)` gives a client with other settings, sharing the connections
and the token. So does `client.vrack.with_options(...)` for one section.

**Retries** are off by default. `retry=True` retries up to 3 attempts, waiting 3 to 30
seconds. Only `GET`, `HEAD` and `DELETE` are retried, on 429, 503 and 504, and a `Retry-After`
header is followed. `POST`, `PUT` and `PATCH` are never retried: on this API they can start
tasks or place orders. In tests, `retry_sleep=lambda s: None` retries a mocked `503` at once.

**Redirects are not followed.** The API does not redirect. A `3xx` comes back as an
`ApiError`, so you see it. Following it would send the request, and its token, to a route
that `read_only` and `allowed_operations` did not check. This differs from the Go SDK, which
follows redirects.

**Debug logs** go to the `ovhcloud` logger at `DEBUG` level. Show them with:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
client = ovhcloud.Client(debug=True)
```

Credential headers are always hidden. `debug_bodies=True` adds the bodies, which often hold
secrets: use it only on test data.

**Planning changes with a dry run.** With `dry_run=True`, a program reads the real state of the
account, but changes nothing. A call that would change something is not sent. It raises
`ovhcloud.DryRunError`, which holds what would have been sent:

```python
from ovhcloud.api.vrack import models

client = ovhcloud.Client(dry_run=True)
try:
    client.vrack.create_cloud_project(
        "pn-1", models.CreateCloudProjectRequest(project="0123456789abcdef")
    )
except ovhcloud.DryRunError as dry:
    print(dry.method, dry.url, dry.body.decode())
```

```text
POST https://api.eu.ovhcloud.com/v1/vrack/pn-1/cloudProject {"project":"0123456789abcdef"}
```

Printed, the error itself reads:

```text
vrack.create_cloud_project (POST https://api.eu.ovhcloud.com/v1/vrack/pn-1/cloudProject) not sent: dry run
```

`operation` is the operation's name (`""` when the route is unknown), `url` is the full URL
with its query, `headers` the headers, and `body` the JSON body (`None` when there is none). No
OAuth2 token is fetched for such a call, and the credential headers (`Authorization`,
`Cookie`...) are left out. It is never retried. The policy still applies first: with
`read_only` or `allowed_operations`, a refused call still raises `NotAllowedError`.

**Watching every call with hooks.** A hook sees every call the client makes, with the operation
it calls. Use it to keep an audit log, or to refuse some calls:

```python
import logging


def no_deprecated(call: ovhcloud.CallInfo) -> None:
    if call.operation is not None and call.operation.deprecated:
        raise ValueError(f"{call.operation.name} is deprecated")


def audit(call: ovhcloud.CallInfo, result: ovhcloud.CallResult) -> None:
    logging.info(
        "%s %s: %d in %.3fs (%d attempts, query %s): %s",
        call.method, call.path, result.status_code, result.duration,
        result.attempts, result.query_id, result.error,
    )


client = ovhcloud.Client(before_request=no_deprecated, after_request=audit)
```

- `CallInfo` has the `operation` (`None` when the route is unknown), `method`, `path`, `query`
  and `body`. It never holds the token. It is frozen: a hook cannot change the call.
  `call.read_only` is `True` for `GET` and `HEAD`, also for an unknown route.
- A before hook runs once per call, just before it is sent. Retries do not run it again. If it
  raises an exception, nothing is sent, and the caller gets a `HookRefusedError` whose
  `__cause__` is that exception.
- An after hook runs once per call, after the retries. It also sees the calls that were not
  sent: refused by the policy or by a before hook, malformed, or stopped by a dry run. Then
  `status_code` and `attempts` are 0. An exception it raises goes to the caller.
- Several hooks run in the order they were given: pass a list.
- A client is shared, so calls made at the same time from several threads run the same hook
  at the same time. A hook must be safe for that: protect what it writes with a lock, for
  example.
- A `KeyboardInterrupt`, or the cancellation of an async call, is not a refusal. The after
  hooks still see it, with `result.error` set, and then it goes on.
- Each page of an `all_` iterator is a separate call, so the hooks run once per page.
- `AsyncClient` takes plain functions or `async def` functions. A plain one runs in the event
  loop, so it must not block.

In one call, the steps run in this order: find the operation, check the path, check
`read_only` and `allowed_operations`, check the body, run the before hooks, stop if it is a dry
run, then send. The after hooks run last, whatever happened.

**X-Schemas-Version.** The v2 API serves several versions of its contract. The SDK sends, with
every v2 request, the version its types were generated from, so your account's own setting
does not change what the SDK receives.

---

## 8. Calling any endpoint

The sections are a convenience over one call, which you can make yourself, for a route newer
than your SDK version for example. It returns plain dicts and lists:

```python
me = client.get("/v1/me")
client.post("/v1/me/contact", {"email": "ops@example.com"})
for policy in client.iterate("/v2/iam/policy"):  # a v2 list, page by page
    print(policy["name"])
```

- Build a path with parameters with `ovhcloud.path`. It escapes each value, like Go's
  `ovh.Path`. Without it, `1.2.3.0/24` in an f-string calls another route:

  ```python
  client.get(ovhcloud.path("/v1/vrack/{serviceName}/ip/{ip}", serviceName=name, ip=ip))
  ```

- Pass `result=` to get a typed result instead of dicts. It is decoded like the result of a
  generated method: a response that does not match still comes back:

  ```python
  ids = client.get("/v1/vrack", result=list[str])
  ```

- A dict body is sent as it is, with the API names you give.

The client's policy, retries, errors and debug logs apply the same way.

---

## 9. Async programs

For asyncio programs (FastAPI, aiohttp...), use `ovhcloud.AsyncClient`. It takes the same
arguments as `Client` and has the same sections and methods, with `await`:

```python
import asyncio

import ovhcloud


async def main() -> None:
    async with ovhcloud.AsyncClient() as client:
        account = await client.me.get_account_details()
        async for project in client.public_cloud.all_projects():
            print(project.name)


asyncio.run(main())
```

- Iterators (`all_` methods, `client.iterate`) are async iterators: use `async for`.
- Wait with the `async_` forms, and `await`: `ovhcloud.async_wait_ready`,
  `async_wait_task`, `async_wait_gone`, `async_wait`. Their `get` returns an awaitable:
  `await ovhcloud.async_wait_ready(lambda: client.public_cloud.get_instance(pid, iid))`.
- Run calls at the same time with `asyncio.gather`. They share the connections, and one token.
- `token_source` takes an object with `async def token()`. An object with a plain `token()`
  works too, but it is called in the event loop, so it must not block.
- `http_client` takes an `httpx.AsyncClient`.
- Use one `AsyncClient` in one event loop. Close it with `await client.aclose()`, or use
  `async with`.

The index (`index/<section>.jsonl`) lists the methods of `Client`. `AsyncClient` has the same
ones.

---

## 10. Testing your code

Your tests do not need the network or real credentials. Mock the API with
[respx](https://lundberg.github.io/respx/) or `httpx.MockTransport`, and give the client a
fixed token:

- `token_source=ovhcloud.StaticTokenSource("test-token")`: no credentials, and no call to the
  token endpoint.
- Mock the region's API host: `https://api.eu.ovhcloud.com` by default, or the one of
  `region=`. Paths have their version: `/v1/me`. `endpoint=` points the client at a test
  server instead.
- `retry_sleep=lambda seconds: None`, if you use `retry=`: a mocked `503` is retried at once.

```python
import pytest
import respx

import ovhcloud


@pytest.fixture
def client():
    with ovhcloud.Client(
        token_source=ovhcloud.StaticTokenSource("test-token"),
        retry=True,
        retry_sleep=lambda seconds: None,
    ) as client:
        yield client


def test_account(client):
    with respx.mock(base_url="https://api.eu.ovhcloud.com") as api:
        api.get("/v1/me").respond(json={"nichandle": "ab12345-ovh"})
        api.get("/v1/me/sshKey").respond(404, json={"message": "not found"})

        assert client.me.get_account_details().nichandle == "ab12345-ovh"
        with pytest.raises(ovhcloud.NotFoundError):
            client.me.list_ssh_keys()
```

Without respx, pass your own `httpx.Client` with a `MockTransport`:

```python
import httpx


def handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/v1/me/sshKey"
    return httpx.Response(200, json=["my-key"])


client = ovhcloud.Client(
    token_source=ovhcloud.StaticTokenSource("test-token"),
    http_client=httpx.Client(transport=httpx.MockTransport(handler)),
)
assert client.me.list_ssh_keys() == ["my-key"]
```

To test code that takes a result, build the model yourself, with its required fields and the
fields your code reads. Its class is in the method's signature. With the widget example of
section 4:

```python
from unittest import mock

fake = mock.Mock()
fake.widget.get_widget.return_value = models.WidgetWidget(id="w-1", name="web", size=2)
```

With `AsyncClient`, use one client per event loop. pytest-asyncio may run each test in its
own loop: create the client in the test, or in a fixture with the same loop scope, not at
module level. `respx` mocks `httpx.AsyncClient` too, and an async `retry_sleep` skips the
waits: `async def no_sleep(seconds): pass`.

---

## 11. Observability

The SDK's own hooks, `before_request` and `after_request` (section 7), see each call once,
with the operation it calls, its status, its `X-Ovh-Queryid` and the number of attempts. They
also see the calls that were refused and never sent. Use them for an audit log.

The SDK has no tracing or metrics of its own. It sends every request, token requests
included, through one `httpx` client. Give it your own, and use what httpx offers:

- **Event hooks** see each request and response. The `X-Ovh-Queryid` header identifies a call
  for OVHcloud support, also when it succeeds. On an error it is in `err.query_id` too.

  ```python
  import httpx

  def log_query_id(response: httpx.Response) -> None:
      logging.info("%s %s: %s %s", response.request.method, response.request.url.path,
                   response.status_code, response.headers.get("X-Ovh-Queryid"))

  client = ovhcloud.Client(http_client=httpx.Client(event_hooks={"response": [log_query_id]}))
  ```

- **OpenTelemetry**: the
  [httpx instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/httpx/httpx.html)
  makes a span per request. Call
  `HTTPXClientInstrumentor().instrument_client(http_client)` on the client you pass, or
  `HTTPXClientInstrumentor().instrument()` before you create the SDK's client, for every httpx
  client, the SDK's own included.

With your own `http_client`:

- The SDK still sets on each request the `Authorization`, `User-Agent` and the other headers
  it needs, and applies `timeout=` when you give it.
- The TLS and proxy arguments of `Client` cannot be used. Set them on your httpx client.
- httpx's own default timeout is 5 seconds. Pass `timeout=` to the SDK, or set it on your
  client.
- `client.close()` does not close it: you own it.
- Each retry is a new request, so hooks and spans see each attempt.

---

## 12. Troubleshooting

**`no credentials`**: `OVH_CLIENT_ID` and `OVH_CLIENT_SECRET` are not set where the program
runs.

**`401 You must login first`**: the API did not accept your token. Check that `OVH_REGION`
matches the region of your account and service account, then that the credentials are valid.

**`403 This call has not been granted`**: you are authenticated, but your service account lacks
permission for that route. The method's docstring names the IAM actions it needs: grant them
with an
[IAM policy](https://docs.ovhcloud.com/en/guides/account-and-service-management/account-information/iam-policy-ui).

**`404 Not Found`**: usually a wrong identifier, such as a project ID from another region.

**The call hangs**: you have no timeout. Add `timeout=30`.

**See exactly what is sent**: add `debug=True`. Credential headers are hidden, so the output
is safe to paste into a bug report.

---

## Contributing

Issues and pull requests are welcome: read [CONTRIBUTING.md](CONTRIBUTING.md) first, since
`src/ovhcloud/api/` is generated. Report bugs at <https://github.com/ovh/sdk-python/issues>.

## License

Copyright 2026 OVH SAS. Licensed under the [Apache License 2.0](LICENSE). See
[LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt) for the full text.

## Related links

- Contribute: [CONTRIBUTING.md](CONTRIBUTING.md)
- Report bugs: <https://github.com/ovh/sdk-python/issues>
- Releases and changes: [CHANGELOG.md](CHANGELOG.md), <https://github.com/ovh/sdk-python/releases>
- The package: [`ovhcloud` on PyPI](https://pypi.org/project/ovhcloud/)
- Examples: [examples/](examples/README.md)
- The API: the OVHcloud developer hub, <https://developers.eu.ovhcloud.com/>, and its
  [API reference](https://developers.eu.ovhcloud.com/reference/)
- Service accounts and IAM: [Managing OVHcloud service accounts](https://docs.ovhcloud.com/en/guides/manage-and-operate/api/manage-service-account),
  [IAM policies](https://docs.ovhcloud.com/en/guides/account-and-service-management/account-information/iam-policy-ui)
