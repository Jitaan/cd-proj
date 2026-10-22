"""Regression tests for C arrays, for-loops and the optimiser.

The optimiser must never change observable output.  In particular a `store`
writes to memory and is not a pure definition of its value operand, so dead
code elimination must keep it.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import service  # noqa: E402


PROGRAMS = {
    "read_first_array": ("""
int main(){
   int n = 10;
   int a[10];
   int b[10];
   int x = 5;
   int y = 5;
   for(int i=0; i<=n-1; i++){
      a[i] = i;
      b[i] = x+y;
   }
   printf("%d\\n", a[5]);
}
""", "5\n"),
    "read_second_array": ("""
int main(){
   int n = 10;
   int a[10];
   int b[10];
   int x = 5;
   int y = 5;
   for(int i=0; i<=n-1; i++){
      a[i] = i;
      b[i] = x+y;
   }
   printf("%d\\n", b[5]);
}
""", "10\n"),
    "array_size_from_declaration": ("""
int main(){
   int a[7];
   for(int i=0; i<7; i++){ a[i] = i*i; }
   printf("%d\\n", a[6]);
}
""", "36\n"),
    "read_in_second_loop": ("""
int main(){
   int a[8];
   for(int i=0; i<8; i++){ a[i] = i+1; }
   int s = 0;
   for(int i=0; i<8; i++){ s += a[i]; }
   printf("%d\\n", s);
}
""", "36\n"),
    "compound_and_incdec": ("""
int main(){
   int a[4];
   for(int i=0; i<4; i++){ a[i] = 1; }
   a[2] += 5;
   a[3] *= 3;
   a[0]--;
   printf("%d %d %d\\n", a[0], a[2], a[3]);
}
""", "0 6 3\n"),
    "non_unit_step": ("""
int main(){
   int a[10];
   for(int i=0; i<10; i+=2){ a[i] = i; }
   printf("%d %d\\n", a[4], a[9]);
}
""", "4 0\n"),
    "computed_index": ("""
int main(){
   int a[10];
   for(int i=0; i<5; i++){ a[i*2] = i+100; }
   int j = 3;
   printf("%d %d\\n", a[6], a[j*2]);
}
""", "103 103\n"),
    "multiple_declarators": ("""
int main(){
   int a, b, c, x;
   a = 10;
   b = 20;
   c = 30;
   x = a + b;
   printf("%d\\n", x);
}
""", "30\n"),
    "multiple_declarators_with_init": ("""
int main(){
   int a = 1, b = 2, c = 3;
   printf("%d\\n", a + b + c);
}
""", "6\n"),
    "for_multiple_init_declarators": ("""
int main(){
   int a[3];
   for(int i = 0, j = 5; i < 3; i++){
      a[i] = j - i;
   }
   printf("%d %d\\n", a[0], a[2]);
}
""", "5 3\n"),
    "global_multiple_declarators": ("""
int g1, g2 = 7, g3;
int main(){
   g1 = 3;
   g3 = 4;
   printf("%d %d %d\\n", g1, g2, g3);
}
""", "3 7 4\n"),
    "while_loop": ("""
int main() {
   int i, sum;
   i = 1;
   sum = 0;
   while (i <= 10) {
      sum = sum + i;
      i = i + 1;
   }
   printf("%d\\n", i);
}
""", "11\n"),
    "while_truthiness": ("""
int main() {
   int i = 3, s = 0;
   while (i) { s = s + i; i = i - 1; }
   printf("%d\\n", s);
}
""", "6\n"),
    "do_while": ("""
int main() {
   int i = 1, s = 0;
   do { s += i; i++; } while (i <= 5);
   printf("%d %d\\n", s, i);
}
""", "15 6\n"),
}


@pytest.mark.parametrize("name", sorted(PROGRAMS))
@pytest.mark.parametrize("mode", ["none", "ai", "all"])
def test_optimiser_preserves_array_output(name, mode):
    source, expected = PROGRAMS[name]
    result = service.run_pipeline(source, mode=mode, lang="c")

    assert result["error"] is None, result["error"]
    assert result["output_before"] == [expected]
    assert result["output_after"] == [expected]
    assert result["match"] is True
