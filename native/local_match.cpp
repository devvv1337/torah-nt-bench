#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using Words=std::vector<std::string>;
struct Unit {std::string text; Words words;};
struct Oriented {std::string text; int unit,direction;};
struct Seed {int unit,start;};
struct Hit {int left,direction,oriented_start,left_start,left_end,right,right_start,length;};
struct Result {int maximum=0; std::uint64_t seed_pairs=0; std::vector<Hit> hits;};

std::uint64_t bounded(std::mt19937_64 &rng,std::uint64_t n) {
    if(!n) throw std::runtime_error("Empty sampling range");
    const auto limit=std::uint64_t(-n)%n;
    std::uint64_t x; do {x=rng();} while(x<limit);
    return x%n;
}
template<class T> void shuffle_exact(T &v,std::mt19937_64 &rng) {
    for(std::size_t i=v.size();i>1;--i) std::swap(v[i-1],v[bounded(rng,i)]);
}
std::string join(const Words &words) {std::string out;for(const auto &w:words)out+=w;return out;}
std::uint64_t shape(const std::string &text,int start,int size) {
    std::array<int,24> seen;seen.fill(-1);int next=0;std::uint64_t code=0;
    for(int j=0;j<size;++j) {
        int c=text[start+j]-'A';
        if(seen[c]<0)seen[c]=next++;
        code=(code<<4)|static_cast<std::uint64_t>(seen[c]);
    }
    return code;
}
int extend(const std::string &a,int i,const std::string &b,int j,int cap) {
    std::array<int,24> forward,backward;forward.fill(-1);backward.fill(-1);
    int length=0;
    while(length<cap && i+length<int(a.size()) && j+length<int(b.size())) {
        int x=a[i+length]-'A',y=b[j+length]-'A';
        if((forward[x]>=0 && forward[x]!=y)||(backward[y]>=0 && backward[y]!=x))break;
        forward[x]=y;backward[y]=x;++length;
    }
    return length;
}

class Matcher {
    int minimum,cap;
    std::vector<Oriented> left;
    std::unordered_map<std::uint64_t,std::vector<Seed>> index;
public:
    std::uint64_t left_starts=0;
    Matcher(const std::vector<Unit> &source,int k,int maximum):minimum(k),cap(maximum) {
        if(k<1||k>16||maximum<k)throw std::runtime_error("Unsupported seed/cap");
        for(int direction:{1,-1})for(int u=0;u<int(source.size());++u) {
            auto text=source[u].text;
            if(direction==-1)std::reverse(text.begin(),text.end());
            int oi=static_cast<int>(left.size());left.push_back({text,u,direction});
            for(int p=0;p+k<=int(text.size());++p) {
                index[shape(text,p,k)].push_back({oi,p});++left_starts;
            }
        }
    }
    Result scan(const std::vector<Unit> &right,bool retain) const {
        Result result;
        for(int r=0;r<int(right.size());++r) {
            const auto &b=right[r].text;
            for(int j=0;j+minimum<=int(b.size());++j) {
                auto found=index.find(shape(b,j,minimum));
                if(found==index.end())continue;
                for(const auto &s:found->second) {
                    ++result.seed_pairs;const auto &a=left[s.unit];
                    int length=extend(a.text,s.start,b,j,cap);
                    if(length<minimum)throw std::runtime_error("Seed pattern disagrees with extension");
                    if(length>result.maximum) {result.maximum=length;result.hits.clear();}
                    if(retain && length==result.maximum) {
                        int original=a.direction==1?s.start:int(a.text.size())-s.start-length;
                        result.hits.push_back({a.unit,a.direction,s.start,original,original+length,r,j,length});
                    }
                    if(!retain && result.maximum==cap)return result;
                }
            }
        }
        return result;
    }
};

Unit read_unit(std::istream &input) {
    std::string line,word;if(!std::getline(input,line))throw std::runtime_error("Truncated input");
    std::istringstream stream(line);Words words;
    while(stream>>word) {
        for(char c:word)if(c<'A'||c>'X')throw std::runtime_error("Invalid encoded letter");
        words.push_back(word);
    }
    return {join(words),words};
}
std::vector<Unit> randomized(const std::vector<Unit> &source,int mode,std::mt19937_64 &rng) {
    auto result=source;
    for(auto &u:result) {
        if(mode==0)shuffle_exact(u.text,rng);
        else {shuffle_exact(u.words,rng);u.text=join(u.words);}
    }
    return result;
}
void print_scores(const std::vector<int> &v) {
    std::cout<<'[';for(std::size_t i=0;i<v.size();++i){if(i)std::cout<<',';std::cout<<v[i];}std::cout<<']';
}
#ifndef BIBLELAB_LOCAL_MATCH_NO_MAIN
int main(int argc,char **argv) {
    try {
        if(argc!=6)throw std::runtime_error("usage: local_match INPUT MIN CAP DRAWS SEED");
        std::ifstream input(argv[1]);if(!input)throw std::runtime_error("Cannot open input");
        int nl,nr; if(!(input>>nl>>nr)||nl<0||nr<0)throw std::runtime_error("Invalid dimensions");
        std::string line;std::getline(input,line);std::vector<Unit> left,right;
        for(int i=0;i<nl;++i)left.push_back(read_unit(input));
        for(int i=0;i<nr;++i)right.push_back(read_unit(input));
        while(std::getline(input,line))if(line.find_first_not_of(" \t\r")!=std::string::npos)throw std::runtime_error("Trailing input");
        int minimum=std::stoi(argv[2]),cap=std::stoi(argv[3]),draws=std::stoi(argv[4]);
        if(draws<0)throw std::runtime_error("Negative draw count");
        std::mt19937_64 rng(std::stoull(argv[5]));Matcher matcher(left,minimum,cap);
        auto observed=matcher.scan(right,true);std::uint64_t right_starts=0;
        for(const auto &u:right)if(int(u.text.size())>=minimum)right_starts+=u.text.size()-minimum+1;
        std::cout<<"{\"maximum\":"<<observed.maximum<<",\"left_oriented_starts\":"<<matcher.left_starts
            <<",\"right_starts\":"<<right_starts<<",\"start_pairs\":"<<matcher.left_starts*right_starts
            <<",\"equal_seed_pairs\":"<<observed.seed_pairs<<",\"maximum_occurrences\":[";
        for(std::size_t i=0;i<observed.hits.size();++i) {
            if(i)std::cout<<',';const auto &h=observed.hits[i];
            std::cout<<"{\"left_unit\":"<<h.left<<",\"direction\":"<<h.direction<<",\"left_oriented_start\":"<<h.oriented_start
                <<",\"left_start\":"<<h.left_start<<",\"left_end\":"<<h.left_end<<",\"right_unit\":"<<h.right
                <<",\"right_start\":"<<h.right_start<<",\"length\":"<<h.length<<'}';
        }
        std::cout<<"],\"reference_maxima\":{";
        for(int mode=0;mode<2;++mode) {
            std::vector<int> scores;scores.reserve(draws);
            for(int i=0;i<draws;++i)scores.push_back(matcher.scan(randomized(right,mode,rng),false).maximum);
            if(mode)std::cout<<',';std::cout<<(mode==0?"\"letters\":" : "\"words\":");print_scores(scores);
        }
        std::cout<<"}}\n";
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
#endif
