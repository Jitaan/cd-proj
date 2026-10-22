"""Regression tests for global arrays, array parameters and 2-D arrays.

These are the cases the old type system got wrong: a global array and an
array parameter both used to be read as a *size* instead of a *type*, and a
two-dimensional array was rejected by the parser.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import service  # noqa: E402


PROGRAMS = {
    "global_array_write": ("""
int g[4];
int main(){
   g[0] = 7;
   g[3] = 9;
   printf("%d %d\\n", g[0], g[3]);
}
""", "7 9\n"),
    "global_array_initialiser": ("""
int g[3] = {4, 5, 6};
int main(){
   printf("%d %d %d\\n", g[0], g[1], g[2]);
}
""", "4 5 6\n"),
    "global_array_loop": ("""
int g[5];
int main(){
   for(int i = 0; i < 5; i++){ g[i] = i * i; }
   printf("%d %d\\n", g[2], g[4]);
}
""", "4 16\n"),
    "global_array_shared": ("""
int g[3];
void bump(int i){ g[i] = g[i] + 1; }
int main(){
   g[0] = 1;
   bump(0);
   bump(0);
   printf("%d\\n", g[0]);
}
""", "3\n"),
    "array_parameter": ("""
int first(int a[3]){ return a[0]; }
int main(){
   int b[3];
   b[0] = 4; b[1] = 5; b[2] = 6;
   printf("%d\\n", first(b));
}
""", "4\n"),
    "array_parameter_unsized": ("""
int first(int a[]){ return a[1]; }
int main(){
   int b[3];
   b[0] = 4; b[1] = 5; b[2] = 6;
   printf("%d\\n", first(b));
}
""", "5\n"),
    "array_parameter_mutates_caller": ("""
void fill(int a[3]){ a[0] = 11; a[2] = 13; }
int main(){
   int b[3];
   fill(b);
   printf("%d %d\\n", b[0], b[2]);
}
""", "11 13\n"),
    "array_parameter_sum": ("""
int sum(int a[4]){
   int s = 0;
   for(int i = 0; i < 4; i++){ s = s + a[i]; }
   return s;
}
int main(){
   int b[4];
   b[0] = 1; b[1] = 2; b[2] = 3; b[3] = 4;
   printf("%d\\n", sum(b));
}
""", "10\n"),
    "two_dimensional": ("""
int main(){
   int m[2][3];
   m[0][0] = 1; m[0][1] = 2; m[0][2] = 3;
   m[1][0] = 4; m[1][1] = 5; m[1][2] = 6;
   printf("%d %d\\n", m[0][2], m[1][0]);
}
""", "3 4\n"),
    "two_dimensional_loop": ("""
int main(){
   int m[2][3];
   for(int i = 0; i < 2; i++){
      for(int j = 0; j < 3; j++){ m[i][j] = i * 3 + j; }
   }
   printf("%d %d\\n", m[0][0], m[1][2]);
}
""", "0 5\n"),
    "two_dimensional_row_sum": ("""
int main(){
   int m[2][3];
   m[0][0] = 1; m[0][1] = 2; m[0][2] = 3;
   m[1][0] = 4; m[1][1] = 5; m[1][2] = 6;
   int s = 0;
   for(int j = 0; j < 3; j++){ s = s + m[1][j]; }
   printf("%d\\n", s);
}
""", "15\n"),
    "local_array_initialiser": ("""
int main(){
   int a[4] = {1, 2, 3, 4};
   printf("%d %d\\n", a[0], a[3]);
}
""", "1 4\n"),
    "array_of_char": ("""
int main(){
   char c[3];
   c[0] = 65; c[1] = 66; c[2] = 67;
   printf("%d %d\\n", c[0], c[2]);
}
""", "65 67\n"),
}


@pytest.mark.parametrize("name", sorted(PROGRAMS))
@pytest.mark.parametrize("mode", ["none", "ai", "all"])
def test_optimiser_preserves_output(name, mode):
    source, expected = PROGRAMS[name]
    result = service.run_pipeline(source, mode=mode, lang="c")

    assert result["error"] is None, result["error"]
    assert result["output_before"] == [expected]
    assert result["output_after"] == [expected]
    assert result["match"] is True
