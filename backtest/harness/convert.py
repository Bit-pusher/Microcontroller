"""Translate AI_SuperTrend_KNN.mq5 into C++ that compiles against shim.h (logic only, no chart)."""
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
out = []
nbuf = None
for line in src.split("\n"):
    m = re.match(r"#property\s+indicator_buffers\s+(\d+)", line)
    if m:
        nbuf = int(m.group(1))
    if line.startswith("#property") or re.match(r"\s*input\s+group\b", line):
        continue
    line = re.sub(r"^input\s+", "", line)
    line = re.sub(r"C'(\d+),(\d+),(\d+)'", r"RGBC(\1,\2,\3)", line)
    line = re.sub(r"(const\s+)?\b(\w+)\s*&\s*(\w+)\[\]", r"\1Arr<\2> &\3", line)
    m = re.match(r"^(\s*)(double|long|int|datetime|string)\s+(\w+\[\](?:\s*,\s*\w+\[\])*)\s*;(.*)$", line)
    if m:
        names = [n.strip()[:-2] for n in m.group(3).split(",")]
        line = f"{m.group(1)}Arr<{m.group(2)}> {', '.join(names)};{m.group(4)}"
    out.append(line)
print(f"#define DECLARED_BUFFERS {nbuf}")
print("\n".join(out))
