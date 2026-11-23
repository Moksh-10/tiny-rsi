#pragma once
#include "physics.hpp"
#include <filesystem>
namespace ascent {
struct Preferences { bool sound=true; float sensitivity=1; };
std::filesystem::path defaultSavePath();
bool writeSave(const std::filesystem::path& path,const Player& player,Preferences preferences);
bool readSave(const std::filesystem::path& path,Player& player,Preferences& preferences,const std::vector<Rock>& terrain);
}
