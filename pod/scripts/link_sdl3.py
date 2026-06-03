import os

Import("env")

project_dir = env.subst("$PROJECT_DIR")
sdl3_base   = os.path.join(project_dir, "vendor", "SDL3-3.4.10", "i686-w64-mingw32")
include_dir = os.path.join(sdl3_base, "include")
lib_dir     = os.path.join(sdl3_base, "lib")

env.Append(CPPPATH=[include_dir])
env.Append(LIBPATH=[lib_dir])
env.Append(LIBS=["SDL3"])
