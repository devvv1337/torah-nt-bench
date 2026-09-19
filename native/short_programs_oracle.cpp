// Independent absolute-value enumeration, no production catalog or relative keys.
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
struct OracleRow {int group;std::string text;};
std::vector<OracleRow> read_rows(std::istream &in,int count,char maximum) {
    std::vector<OracleRow> rows;
    for(int i=0;i<count;++i) {
        std::string line;if(!std::getline(in,line))throw std::runtime_error("Short oracle input");
        std::istringstream row(line);int group;if(!(row>>group)||group<0)throw std::runtime_error("Bad group");
        std::string word,text;while(row>>word){for(char c:word)if(c<'A'||c>maximum)throw std::runtime_error("Bad rank");text+=word;}
        rows.push_back({group,text});
    }
    return rows;
}
struct OracleEdge {int left,right,length;};
// Inclusion-exclusion: after any two disjoint edges, count eligible third edges.
bool three_edges(const std::vector<OracleEdge> &edges,int length) {
    std::vector<OracleEdge> use;std::map<int,int> left,right;std::set<std::pair<int,int>> present;
    for(auto e:edges)if(e.length>=length){use.push_back(e);++left[e.left];++right[e.right];present.insert({e.left,e.right});}
    if(left.size()<3||right.size()<3)return false;
    for(std::size_t i=0;i<use.size();++i)for(std::size_t j=i+1;j<use.size();++j) {
        auto a=use[i],b=use[j];if(a.left==b.left||a.right==b.right)continue;
        int remaining=int(use.size())-left[a.left]-left[b.left]-right[a.right]-right[b.right];
        for(int l:{a.left,b.left})for(int r:{a.right,b.right})remaining+=present.count({l,r});
        if(remaining>0)return true;
    }
    return false;
}
#ifndef SHORT_PROGRAM_ORACLE_NO_MAIN
int main(int argc,char **argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: short_programs_oracle INPUT MIN CAP");
        int minimum=std::stoi(argv[2]),cap=std::stoi(argv[3]);if(minimum<1||minimum>12||cap<minimum)throw std::runtime_error("Bad lengths");
        std::ifstream in(argv[1]);int nl,nr;if(!(in>>nl>>nr)||nl<0||nr<0)throw std::runtime_error("Bad dimensions");
        std::string line;std::getline(in,line);auto left=read_rows(in,nl,'V'),right=read_rows(in,nr,'X');
        while(std::getline(in,line))if(line.find_first_not_of(" \t\r")!=std::string::npos)throw std::runtime_error("Extra input");
        std::uint64_t mask=(std::uint64_t(1)<<(5*minimum))-1;
        std::unordered_map<std::uint64_t,std::vector<std::pair<int,int>>> index;
        for(int r=0;r<nr;++r) {
            std::uint64_t key=0;const auto &s=right[r].text;
            for(int p=0;p<int(s.size());++p){key=((key<<5)|unsigned(s[p]-'A'))&mask;if(p+1>=minimum)index[key].push_back({r,p+1-minimum});}
        }
        const int c4[4]={-2,-1,1,2},c5[5]={-2,-1,0,1,2};
        std::array<int,7008> scores{};std::array<int,3> maxima{};std::uint64_t seeds=0;
        for(int rule=0;rule<7008;++rule) {
            int kind,span,direction,a,b,t=0,product=0,c=rule%24;
            if(rule<768){kind=0;span=2;direction=rule<384?1:-1;a=c4[(rule/96)%4];b=c4[(rule/24)%4];}
            else if(rule<4608){int x=rule-768;kind=1;span=3;direction=x<1920?1:-1;a=c4[(x/480)%4];b=c5[(x/96)%5];t=c4[(x/24)%4];}
            else{int x=rule-4608;kind=2;span=2;direction=x<1200?1:-1;product=(x/600)%2?1:-1;a=c5[(x/120)%5];b=c5[(x/24)%5];}
            std::map<std::pair<int,int>,int> group_max;
            for(int l=0;l<nl;++l) {
                auto h=left[l].text;if(direction<0)std::reverse(h.begin(),h.end());std::string prediction;prediction.reserve(h.size());
                for(int p=0;p+span<=int(h.size());++p) {
                    int x=h[p]-'A',y=h[p+1]-'A';int rank=(a*x+b*y+product*x*y+(span==3?t*(h[p+2]-'A'):0)+c)%24;
                    if(rank<0)rank+=24;prediction+=char('A'+rank);
                }
                std::uint64_t key=0;
                for(int end=0;end<int(prediction.size());++end) {
                    key=((key<<5)|unsigned(prediction[end]-'A'))&mask;if(end+1<minimum)continue;
                    auto found=index.find(key);if(found==index.end())continue;int p=end+1-minimum;
                    for(auto pos:found->second) {
                        ++seeds;int r=pos.first,rp=pos.second,length=minimum;
                        while(length<cap&&p+length<int(prediction.size())&&rp+length<int(right[r].text.size())
                              &&prediction[p+length]==right[r].text[rp+length])++length;
                        auto pair=std::make_pair(left[l].group,right[r].group);group_max[pair]=std::max(group_max[pair],length);
                    }
                }
            }
            std::vector<OracleEdge> edges;int upper=0;
            for(auto e:group_max){edges.push_back({e.first.first,e.first.second,e.second});upper=std::max(upper,e.second);}
            for(int k=upper;k>=minimum;--k)if(three_edges(edges,k)){scores[rule]=k;break;}
            maxima[kind]=std::max(maxima[kind],scores[rule]);
        }
        int best=*std::max_element(scores.begin(),scores.end());
        std::cout<<"{\"score\":"<<best<<",\"compatible_seed_pairs\":"<<seeds
                 <<",\"opcode_maxima\":{\"pair\":"<<maxima[0]<<",\"triple\":"<<maxima[1]<<",\"product\":"<<maxima[2]<<"},\"rule_scores\":[";
        for(int r=0;r<7008;++r){if(r)std::cout<<',';std::cout<<scores[r];}
        std::cout<<"],\"maximizing_rule_ids\":[";bool first=true;
        for(int r=0;r<7008;++r)if(best>0&&scores[r]==best){if(!first)std::cout<<',';first=false;std::cout<<r;}
        std::cout<<"]}\n";
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
#endif
