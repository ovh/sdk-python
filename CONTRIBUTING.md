# Contributing to sdk-python

This project accepts contributions. To contribute, please pay attention to a few things:

1. your code must follow the coding style rules
2. your code must be unit-tested
3. your code must be documented
4. your work must be signed (see below)
5. you may contribute through GitHub Pull Requests

# How this repository is built

Most of this repository is **generated** from the OVHcloud API's OpenAPI specifications, and
generated again at every release:

- `src/ovhcloud/api/`: one package per API section. **Generated**. Do not edit these files:
  the next release overwrites the change.
- `index/` and `llms.txt`: generated with the code.
- `src/ovhcloud/_core/`: the SDK core (client, authentication, retries, errors, pagination).
  Hand-written.

So the most useful contributions are:

- **Issues**: a wrong type, a missing operation, a confusing name, a bug in the core. Please
  give the API route (every method's docstring starts with it, for example
  `get_vrack calls GET /v1/vrack/{serviceName}`).
- **Pull requests on `src/ovhcloud/_core/`** are reviewed and merged as usual.
- **Pull requests on `src/ovhcloud/api/`** are welcome as a precise description of a problem.
  The maintainers carry the fix into the generator, so it survives the next generation, and
  close the pull request with a link to the release that has it.

A problem in the API's own behaviour or documentation is not something this repository can
fix: report it to OVHcloud support.

# Coding and documentation style

Python code follows PEP 8, formatted and checked with [ruff](https://docs.astral.sh/ruff/), and
type-checked with [pyright](https://github.com/microsoft/pyright) (strict mode on the core).
Every public name has a docstring. Run:

```bash
uv sync
uvx ruff format --check src
uvx ruff check src
uvx pyright --pythonpath .venv/bin/python src/ovhcloud/_core
```

# Submitting modifications

Contributions are submitted through GitHub Pull Requests and follow the DCO defined below.

# Licensing for new files

sdk-python is licensed under the Apache License 2.0. Anything contributed to sdk-python must be
released under this license.

When you add a new file to the project, make sure it has a copyright header that says under
which license it is released:

```python
# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0
```

# Developer Certificate of Origin (DCO)

To improve tracking of contributions to this project we will use a
process modeled on the modified DCO 1.1 and use a "sign-off" procedure
on patches that are being emailed around or contributed in any other
way.

The sign-off is a simple line at the end of the explanation for the
patch, which certifies that you wrote it or otherwise have the right
to pass it on as an open-source patch.  The rules are pretty simple:
if you can certify the below:

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I have
    the right to submit it under the open source license indicated in
    the file; or

(b) The contribution is based upon previous work that, to the best of
    my knowledge, is covered under an appropriate open source License
    and I have the right under that license to submit that work with
    modifications, whether created in whole or in part by me, under
    the same open source license (unless I am permitted to submit
    under a different license), as indicated in the file; or

(c) The contribution was provided directly to me by some other person
    who certified (a), (b) or (c) and I have not modified it.

(d) The contribution is made free of any other party's intellectual
    property claims or rights.

(e) I understand and agree that this project and the contribution are
    public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.


then you just add a line saying

    Signed-off-by: Random J Developer <random@example.org>

using your real name (sorry, no pseudonyms or anonymous contributions.)
