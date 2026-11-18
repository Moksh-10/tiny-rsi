cmake_minimum_required(VERSION 3.24)
project(angry_birds LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
include(FetchContent)
set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(BOX2D_SAMPLES OFF CACHE BOOL "" FORCE)
set(BOX2D_UNIT_TESTS OFF CACHE BOOL "" FORCE)
set(BOX2D_BENCHMARKS OFF CACHE BOOL "" FORCE)
FetchContent_Declare(raylib GIT_REPOSITORY https://github.com/raysan5/raylib.git GIT_TAG 5.5 GIT_SHALLOW TRUE)
FetchContent_Declare(box2d GIT_REPOSITORY https://github.com/erincatto/box2d.git GIT_TAG v3.1.1 GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(raylib box2d)
add_library(simulation src/simulation.cpp src/levels.cpp src/progress.cpp)
target_include_directories(simulation PUBLIC src)
target_link_libraries(simulation PUBLIC box2d)
target_compile_options(simulation PRIVATE -Wall -Wextra -Wpedantic)
add_executable(angry-birds src/main.cpp src/presentation.cpp)
target_link_libraries(angry-birds PRIVATE simulation raylib)
target_compile_definitions(angry-birds PRIVATE ASSET_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}/assets")
if(APPLE)
  set_target_properties(angry-birds PROPERTIES MACOSX_BUNDLE TRUE
    MACOSX_BUNDLE_GUI_IDENTIFIER "com.moksh.slingshotvalley"
    MACOSX_BUNDLE_BUNDLE_NAME "Slingshot Valley"
    MACOSX_BUNDLE_ICON_FILE "icon.icns"
    MACOSX_BUNDLE_SHORT_VERSION_STRING "0.2.0"
    MACOSX_BUNDLE_BUNDLE_VERSION "2")
  add_custom_command(TARGET angry-birds POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:angry-birds>/../Resources"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "${CMAKE_CURRENT_SOURCE_DIR}/assets/icon.icns" "$<TARGET_FILE_DIR:angry-birds>/../Resources/icon.icns"
    COMMAND ${CMAKE_COMMAND} -E create_symlink
      "$<TARGET_FILE:angry-birds>" "${CMAKE_BINARY_DIR}/angry-birds")
endif()
add_custom_command(TARGET angry-birds POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_directory "${CMAKE_CURRENT_SOURCE_DIR}/assets" "$<TARGET_FILE_DIR:angry-birds>/assets")
target_compile_options(angry-birds PRIVATE -Wall -Wextra -Wpedantic)
include(CTest)
option(SLINGSHOT_UI_TESTS "Run graphical menu-flow tests (requires a display)" OFF)
if(BUILD_TESTING)
  add_executable(simulation-tests tests/simulation_test.cpp)
  target_link_libraries(simulation-tests PRIVATE simulation)
  add_test(NAME simulation COMMAND simulation-tests)
  set_tests_properties(simulation PROPERTIES TIMEOUT 30)
  if(SLINGSHOT_UI_TESTS)
    add_test(NAME ui-flow COMMAND angry-birds --test-ui)
    set_tests_properties(ui-flow PROPERTIES TIMEOUT 60)
  endif()
endif()
