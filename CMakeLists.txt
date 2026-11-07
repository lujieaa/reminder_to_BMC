cmake_minimum_required(VERSION 3.16)

project(SupportPrompt VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Widgets Network)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Widgets Network)

# 可复用的静态库：宿主只需链接 SupportPrompt 并调用 SupportPrompt::SupportPrompt
add_library(SupportPrompt STATIC
    include/supportprompt/supportprompt.h
    include/supportprompt/supportpromptconfig.h
    include/supportprompt/promptpolicy.h
    src/supportprompt.cpp
    src/supportpromptconfig.cpp
    src/supportpromptdialog.h
    src/supportpromptdialog.cpp
    src/supportclient.h
    src/supportclient.cpp
    src/localstore.h
    src/localstore.cpp
    src/promptcatalog.h
    src/promptcatalog.cpp
    src/promptpolicy.cpp
    resources/supportprompt.qrc
)

target_include_directories(SupportPrompt
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_link_libraries(SupportPrompt
    PUBLIC
        Qt${QT_VERSION_MAJOR}::Widgets
        Qt${QT_VERSION_MAJOR}::Network
)

# 演示宿主：模拟“每次 PDF 处理成功”后调用模块
add_executable(SupportPromptDemo
    demo/main.cpp
    demo/demo.qrc
)

target_link_libraries(SupportPromptDemo PRIVATE SupportPrompt)

# 纯 C++ 策略测试（不依赖 Qt，方便 CI 快速校验）
enable_testing()

add_executable(test_promptpolicy
    tests/test_promptpolicy.cpp
    src/promptpolicy.cpp
)

target_include_directories(test_promptpolicy PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
add_test(NAME promptpolicy COMMAND test_promptpolicy)
