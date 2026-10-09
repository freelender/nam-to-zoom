cmake_minimum_required(VERSION 3.20)
project(nam2zoom_core_render LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
if(MSVC)
  set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreaded)
endif()

if(NOT CORE_ROOT)
  message(FATAL_ERROR "Set CORE_ROOT to the pinned NeuralAmpModelerCore checkout")
endif()

file(GLOB CORE_SOURCES "${CORE_ROOT}/NAM/*.cpp" "${CORE_ROOT}/NAM/*/*.cpp")
add_executable(core_render "${CMAKE_CURRENT_SOURCE_DIR}/renderer_main.cpp"
  "${CORE_ROOT}/Dependencies/AudioDSPTools/dsp/wav.cpp" ${CORE_SOURCES})
target_include_directories(core_render PRIVATE
  "${CORE_ROOT}" "${CORE_ROOT}/tools"
  "${CORE_ROOT}/Dependencies/eigen"
  "${CORE_ROOT}/Dependencies/nlohmann"
  "${CORE_ROOT}/Dependencies/AudioDSPTools/dsp")
target_compile_definitions(core_render PRIVATE NAM_ENABLE_A2_FAST NOMINMAX WIN32_LEAN_AND_MEAN)
