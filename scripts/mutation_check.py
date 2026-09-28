"""Mutation check: deliberately break one critical behaviour at a time and
confirm the test suite FAILS. A mutant that "SURVIVED" means a test is not
actually protecting that behaviour.

    .venv/bin/python scripts/mutation_check.py

Each mutant edits a file, runs pytest, and always restores the file.

AI-ASSISTED (Claude Code): written to verify the AI-generated tests were not
vacuous. Its first run found two real test-suite problems (see
docs/AI_COLLABORATION.md).
"""
import subprocess
MUTANTS = [
  ("redis Lua dedupe removed", "quiz_server/store/redis_store.py",
   "if redis.call('HSETNX', KEYS[1], ARGV[1], ARGV[2]) == 0 then", "if redis.call('HSET', KEYS[1], ARGV[1], ARGV[2]) == 99 then"),
  ("memory dedupe removed", "quiz_server/store/memory.py",
   "        if key in s.answers:\n", "        if False:\n"),
  ("served timer resets on reconnect", "quiz_server/store/memory.py",
   "return self._s(quiz_id).served.setdefault((user_id, question_id), ts)",
   "self._s(quiz_id).served[(user_id, question_id)] = ts; return ts"),
  ("coalescing window removed", "quiz_server/hub.py",
   "                await asyncio.sleep(self._interval)\n            except asyncio.CancelledError:",
   "                await asyncio.sleep(0)\n            except asyncio.CancelledError:"),
  ("leaderboard order reversed in redis", "quiz_server/store/redis_store.py",
   "p.zrange(lb, 0, top_n - 1, withscores=True)", "p.zrevrange(lb, 0, top_n - 1, withscores=True)"),
  ("not-served check removed", "quiz_server/service.py",
   "        if served is None:\n            return self._reject", "        if served is None and False:\n            return self._reject"),
  ("bus publish skipped", "quiz_server/hub.py",
   "            await self._bus.publish(quiz_id)\n", "            pass\n"),
  ("server-side elapsed time ignored", "quiz_server/service.py",
   "        elapsed = received - served\n", "        elapsed = 0.0\n"),
]
for name, path, old, new in MUTANTS:
    src = open(path).read(); assert old in src, name
    open(path, "w").write(src.replace(old, new, 1))
    try:
        r = subprocess.run([".venv/bin/pytest", "-q", "-x", "--timeout", "15", "-p", "no:warnings"],
                           capture_output=True, text=True, timeout=120)
        failed = [l for l in r.stdout.splitlines() if l.startswith("FAILED")]
        last = failed[0][:110] if failed else r.stdout.strip().splitlines()[-1]
        verdict = "CAUGHT " if r.returncode else "SURVIVED"
    except subprocess.TimeoutExpired:
        verdict, last = "HUNG   ", "timeout"
    finally:
        open(path, "w").write(src)
    print(f"{verdict} | {name:36s} | {last}", flush=True)
