# Operation index

One file per API section, `<section>.jsonl` (the section's module name), with one JSON object
per line: each method of the SDK and the route it calls. 7535 methods in
80 files. It is generated with the SDK's code at each release, from the
same data, so it always matches it.

Find the method of a route:

```shell
grep -h '"path":"/v1/vrack/{serviceName}"' index/*.jsonl
```

To list what a program needs, collect the `iam` of the methods it calls: those are the
actions to grant its service account. Find the methods that need one action:

```shell
grep -h '"vrack:apiovh:get"' index/*.jsonl
```

Fields:

| Field | Meaning |
|---|---|
| `section` | The API section: its module name and client attribute (`public_cloud`). |
| `method` | The method name. Call `client.<section attribute>.<method>(...)`. |
| `kind` | `call`: one request. `pages`: an iterator over a list paginated by cursor. `each`: an iterator that lists IDs with `lists`, then gets each object with `fetches`. |
| `http`, `path` | The route, with its API version. For `each`, the route of the list. |
| `summary` | The API's one-line description, when it has one. |
| `signature` | The method's Python signature. `models.X` is a type of the section's `models` module. |
| `iam` | The IAM actions the call requires: a 403 means the service account's policy lacks one. For `each`, those of the list and of the fetch. Absent when the API declares none. |
| `deprecated` | Present and true when the API has deprecated the operation. |
| `id` | The operation's name in the SDK: what errors show, and what `read_only` and `allowed_operations` match. |
| `import` | The section's module. Its client attribute is its last part: `ovhcloud.api.public_cloud` is `client.public_cloud`. |
