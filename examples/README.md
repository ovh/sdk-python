# Examples

Small programs that use the OVHcloud Python SDK. Each one is a single file. Read its docstring
first: it lists the environment variables it needs.

| File | What it shows | Changes the account |
|---|---|---|
| [account.py](account.py) | `GET /v1/me`: the details of your account. Start here. | no |
| [list-and-get.py](list-and-get.py) | list with an `all_` iterator, then get one object | no |
| [create-and-wait.py](create-and-wait.py) | create a Public Cloud network, `wait_ready`, delete it, `wait_gone` | yes |
| [dns-record.py](dns-record.py) | create a DNS record, then refresh the zone | yes |
| [cart-order.py](cart-order.py) | order with a cart: add a domain, read the price, stop before payment | no order is placed |
| [errors.py](errors.py) | `except NotFoundError`, `ForbiddenError`, `ApiError` | no |
| [vrack.py](vrack.py) | every vRack, with the Public Cloud projects in it | no |

## Run one

Credentials come from the environment. Never write them in the code.

```shell
export OVH_CLIENT_ID=...  OVH_CLIENT_SECRET=...
export OVH_REGION=eu          # or ca, us
python examples/account.py
```

Python 3.11 or later, with the SDK installed: `pip install ovhcloud`.

`account.py` is the plain quick start, with `ovhcloud.Client()`. The other read-only examples
create their client with `read_only=True`: they cannot change anything, whatever the service
account may do. The examples that change the account run on a test project or a test zone.

## Type-check them

```shell
cd examples
pyright
```

`pyrightconfig.json` checks them in strict mode.
