// Keep the pinned NAM renderer's implementation; report malformed-model errors
// through the backend log instead of the platform's unhandled-exception dialog.
#define main nam_core_render_main
#include "render.cpp"
#undef main

int main(int argc, char* argv[])
{
  try { return nam_core_render_main(argc, argv); }
  catch (const std::exception& error) {
    std::cerr << "NAM rendering failed: " << error.what() << '\n';
    return 2;
  }
}
