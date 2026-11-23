#pragma once
#include "raylib.h"
#include <string>
inline std::string resourceRoot(){
 const std::string executable=GetApplicationDirectory();
 for(const auto& path:{executable+"../Resources",executable+"assets",executable+"../share/the-ascent",std::string(ASCENT_ASSET_DIR)})
  if(FileExists((path+"/shaders/world.vs").c_str()))return path;
 return ASCENT_ASSET_DIR;
}
