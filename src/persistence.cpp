#include "persistence.hpp"
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <string>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif
namespace ascent {
std::filesystem::path defaultSavePath() {
 std::filesystem::path directory;
#ifdef _WIN32
 if(const char* base=std::getenv("LOCALAPPDATA"))directory=std::filesystem::path(base)/"TheAscent";
#elif defined(__APPLE__)
 if(const char* base=std::getenv("HOME"))directory=std::filesystem::path(base)/"Library/Application Support/TheAscent";
#else
 if(const char* base=std::getenv("XDG_DATA_HOME"))directory=std::filesystem::path(base)/"the-ascent";
 else if(const char* home=std::getenv("HOME"))directory=std::filesystem::path(home)/".local/share/the-ascent";
#endif
 if(directory.empty())directory=std::filesystem::temp_directory_path()/"the-ascent";
 return directory/"ascent.save";
}
static bool valid(const Player& p,Preferences prefs) {
 return std::isfinite(p.position.x)&&std::isfinite(p.position.y)&&std::isfinite(p.best)&&std::isfinite(p.elapsed)&&std::isfinite(p.runBest)&&std::isfinite(prefs.sensitivity)
  &&std::abs(p.position.x)<=25&&p.position.y>=.4f&&p.position.y<=70&&p.best>=0&&p.best<=75&&p.runBest>=0&&p.runBest<=p.best&&p.elapsed>=0&&p.elapsed<=100000000&&p.falls>=0&&prefs.sensitivity>=.49f&&prefs.sensitivity<=1.51f;
}
bool writeSave(const std::filesystem::path& path,const Player& player,Preferences preferences) {
 if(!valid(player,preferences))return false;
 std::error_code ec;if(!path.parent_path().empty())std::filesystem::create_directories(path.parent_path(),ec);if(ec)return false;
 auto temporary=path;temporary+=".tmp";
 std::ofstream out(temporary,std::ios::trunc);if(!out)return false;
 out<<std::setprecision(9)<<"ASCENT_2\n"<<player.position.x<<' '<<player.position.y<<' '<<player.best<<' '<<player.elapsed<<' '<<player.falls<<' '<<player.runBest<<' '<<preferences.sound<<' '<<preferences.sensitivity<<'\n';
 out.flush();if(!out)return false;out.close();if(!out)return false;
#ifdef _WIN32
 // Unlike filesystem::rename on Windows, this replaces an existing save atomically.
 if(!MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)){std::filesystem::remove(temporary,ec);return false;}
#else
 std::filesystem::rename(temporary,path,ec);if(ec){std::filesystem::remove(temporary,ec);return false;}
#endif
 return true;
}
bool readSave(const std::filesystem::path& path,Player& player,Preferences& preferences,const std::vector<Rock>& terrain) {
 std::ifstream in(path);std::string magic;Player candidate;Preferences prefs;
 if(!(in>>magic)||(magic!="ASCENT_1"&&magic!="ASCENT_2"))return false;
 if(!(in>>candidate.position.x>>candidate.position.y>>candidate.best>>candidate.elapsed>>candidate.falls))return false;
 if(!std::isfinite(candidate.best)||candidate.best<0)return false;
 if(magic=="ASCENT_2"){
  if(!(in>>candidate.runBest))return false;
 }else{
  // Version 1 mixed lifetime best and run progress. Retain the lifetime record,
  // and safely reconstruct run progress from the resumed altitude.
  candidate.runBest=std::clamp(candidate.position.y-.55f,0.f,candidate.best);
 }
 if(!(in>>prefs.sound>>prefs.sensitivity)||!valid(candidate,prefs))return false;

 for(const Rock& rock:terrain)if(collide(candidate.position,.5f,rock).hit)return false;
 candidate.tip=candidate.position+Vec{2,1.7f};player=candidate;preferences=prefs;return true;
}
}
