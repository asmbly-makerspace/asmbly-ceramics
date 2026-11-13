"""Asmbly Makerspace's ceramics studio app: drop-offs, kiln loads and firings (epic #1).

- `domain`: the entities, their states and the stories' rules, in plain Python.
- `ports`: what the app needs from outside (records, photos, email, sign-in, the clock),
  each a `Protocol`.
- `adapters.memory`: an in-memory fake of each port, which the tests use.
"""
