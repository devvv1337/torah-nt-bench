// Independent algorithm check: no production matcher, relative signatures or RNG.
// Materialize all 768 complete literal predictions, look up exact Greek strings,
// then enumerate disjoint edge triples instead of augmenting paths.
#include <algorithm>
#include <array>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

struct Row {int group;std::string text;};
std::vector<Row> read_rows(std::istream &in,int count,char maximum) {
    std::vector<Row> rows;
    for(int i=0;i<count;++i) {
        std::string line;if(!std::getline(in,line))throw std::runtime_error("Short oracle input");
        std::istringstream row(line);int group;if(!(row>>group)||group<0)throw std::runtime_error("Bad group");
        std::string word,text;
        while(row>>word){for(char c:word)if(c<'A'||c>maximum)throw std::runtime_error("Bad rank");text+=word;}
        rows.push_back({group,text});
    }
    return rows;
}
struct Edge {int left,right,length;};
bool has_three(const std::vector<Edge> &edges,int k) {
    std::vector<Edge> eligible;std::set<int> l,r;
    for(auto edge:edges)if(edge.length>=k){eligible.push_back(edge);l.insert(edge.left);r.insert(edge.right);}
    if(l.size()<3||r.size()<3)return false;
    for(std::size_t i=0;i<eligible.size();++i)for(std::size_t j=i+1;j<eligible.size();++j) {
        const auto &a=eligible[i],&b=eligible[j];if(a.left==b.left||a.right==b.right)continue;
        for(std::size_t t=j+1;t<eligible.size();++t) {
            const auto &c=eligible[t];
            if(c.left!=a.left&&c.left!=b.left&&c.right!=a.right&&c.right!=b.right)return true;
        }
    }
    return false;
}
int main(int argc,char **argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: contextual_oracle INPUT MIN CAP");
        int minimum=std::stoi(argv[2]),cap=std::stoi(argv[3]);if(minimum<1||cap<minimum)throw std::runtime_error("Bad lengths");
        std::ifstream in(argv[1]);int nl,nr;if(!(in>>nl>>nr)||nl<0||nr<0)throw std::runtime_error("Bad dimensions");
        std::string line;std::getline(in,line);auto left=read_rows(in,nl,'V'),right=read_rows(in,nr,'X');
        while(std::getline(in,line))if(line.find_first_not_of(" \t\r")!=std::string::npos)throw std::runtime_error("Extra input");
        std::unordered_map<std::string,std::vector<std::pair<int,int>>> greek;
        for(int r=0;r<nr;++r)for(int p=0;p+minimum<=int(right[r].text.size());++p)
            greek[right[r].text.substr(p,minimum)].push_back({r,p});
        std::array<int,768> scores{};unsigned long long seeds=0;
        const std::array<int,4> co={-2,-1,1,2};
        for(int rule=0;rule<768;++rule) {
            int direction=rule<384?1:-1,a=co[(rule/96)%4],b=co[(rule/24)%4],c=rule%24;
            std::map<std::pair<int,int>,int> group_max;
            for(int l=0;l<nl;++l) {
                auto text=left[l].text;if(direction<0)std::reverse(text.begin(),text.end());
                std::string prediction;
                for(int i=0;i+1<int(text.size());++i) {
                    int rank=(a*(text[i]-'A')+b*(text[i+1]-'A')+c)%24;
                    if(rank<0)rank+=24;prediction+=char('A'+rank);
                }
                for(int p=0;p+minimum<=int(prediction.size());++p) {
                    auto matches=greek.find(prediction.substr(p,minimum));if(matches==greek.end())continue;
                    for(const auto &position:matches->second) {
                        ++seeds;int r=position.first,rp=position.second,length=minimum;
                        while(length<cap&&p+length<int(prediction.size())&&rp+length<int(right[r].text.size())
                            &&prediction[p+length]==right[r].text[rp+length])++length;
                        auto key=std::make_pair(left[l].group,right[r].group);
                        group_max[key]=std::max(group_max[key],length);
                    }
                }
            }
            std::vector<Edge> edges;int upper=0;
            for(const auto &e:group_max){edges.push_back({e.first.first,e.first.second,e.second});upper=std::max(upper,e.second);}
            for(int k=upper;k>=minimum;--k)if(has_three(edges,k)){scores[rule]=k;break;}
        }
        int maximum=*std::max_element(scores.begin(),scores.end());
        std::cout<<"{\"score\":"<<maximum<<",\"compatible_seed_pairs\":"<<seeds<<",\"rule_scores\":[";
        for(int r=0;r<768;++r){if(r)std::cout<<',';std::cout<<scores[r];}
        std::cout<<"],\"maximizing_rule_ids\":[";bool first=true;
        for(int r=0;r<768;++r)if(maximum>0&&scores[r]==maximum){if(!first)std::cout<<',';first=false;std::cout<<r;}
        std::cout<<"]}\n";
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
