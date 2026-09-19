// FAM-004: fixed two-neighbor arithmetic, three distinct group pairs.
// Only input alphabet, exact RNG, and word permutation utilities are reused.
#define BIBLELAB_LOCAL_MATCH_NO_MAIN
#include "local_match.cpp"
#undef BIBLELAB_LOCAL_MATCH_NO_MAIN
#include <map>
#include <set>
#include <functional>

struct ContextUnits {std::vector<Unit> units;std::vector<int> groups;};
ContextUnits context_read(std::istream &in,int n) {
    ContextUnits out;
    for(int i=0;i<n;++i) {
        std::string line;if(!std::getline(in,line))throw std::runtime_error("Missing contextual unit");
        std::istringstream row(line);int group;
        if(!(row>>group)||group<0)throw std::runtime_error("Invalid contextual group");
        std::string rest;std::getline(row,rest);std::istringstream text(rest+'\n');
        out.groups.push_back(group);out.units.push_back(read_unit(text));
    }
    return out;
}
ContextUnits context_types(const ContextUnits &source,std::mt19937_64 &rng) {
    std::map<std::size_t,std::set<std::string>> unique;
    for(const auto &u:source.units)for(const auto &w:u.words)unique[w.size()].insert(w);
    std::unordered_map<std::string,std::string> substitution;
    for(const auto &entry:unique) {
        std::vector<std::string> original(entry.second.begin(),entry.second.end()),permuted=original;
        shuffle_exact(permuted,rng);
        for(std::size_t i=0;i<original.size();++i)substitution[original[i]]=permuted[i];
    }
    auto out=source;
    for(auto &u:out.units){for(auto &w:u.words)w=substitution.at(w);u.text=join(u.words);}
    return out;
}
void context_save(const std::string &path,const ContextUnits &left,const ContextUnits &right) {
    std::ofstream out(path);if(!out)throw std::runtime_error("Cannot save contextual reference");
    out<<left.units.size()<<' '<<right.units.size()<<'\n';
    for(const auto *side:{&left,&right})for(std::size_t i=0;i<side->units.size();++i) {
        out<<side->groups[i];for(const auto &w:side->units[i].words)out<<' '<<w;out<<'\n';
    }
    if(!out)throw std::runtime_error("Cannot finish contextual reference");
}
int mod24(int x){int q=x%24;return q<0?q+24:q;}
constexpr int coefficients[4]={-2,-1,1,2};
struct Prediction {std::string text;int unit,direction,base;};
struct ContextHit {int prediction,start,right,rstart,maximum;};
using ContextGraph=std::map<std::pair<int,int>,ContextHit>;
struct ContextResult {
    int score=0;std::uint64_t seed_pairs=0;
    std::array<int,768> rule_scores{};
    std::map<int,std::vector<ContextHit>> winners;
};

// Ascending group traversal with augmenting paths (not a greedy triple).
std::vector<ContextHit> context_matching(const ContextGraph &graph,int k) {
    std::map<int,std::vector<std::pair<int,const ContextHit *>>> adjacency;
    for(const auto &edge:graph)if(edge.second.maximum>=k)
        adjacency[edge.first.first].push_back({edge.first.second,&edge.second});
    if(adjacency.size()<3)return {};
    std::map<int,std::pair<int,const ContextHit *>> matched;
    std::function<bool(int,std::set<int>&)> augment=[&](int left,std::set<int> &seen) {
        for(const auto &edge:adjacency.at(left)) {
            if(!seen.insert(edge.first).second)continue;
            auto old=matched.find(edge.first);
            if(old==matched.end()||augment(old->second.first,seen)) {
                matched[edge.first]={left,edge.second};return true;
            }
        }
        return false;
    };
    for(const auto &row:adjacency) {
        std::set<int> seen;augment(row.first,seen);
        if(matched.size()==3) {
            std::vector<ContextHit> out;for(const auto &edge:matched)out.push_back(*edge.second.second);
            return out;
        }
    }
    return {};
}

class ContextMatcher {
    const ContextUnits &left;int minimum,cap;
    std::unordered_map<std::uint64_t,std::vector<Seed>> index;
    std::uint64_t relative_key(const std::string &s,int p) const {
        std::uint64_t key=0;
        for(int j=1;j<minimum;++j)key=(key<<5)|static_cast<unsigned>(mod24(s[p+j]-s[p]));
        return key;
    }
public:
    std::vector<Prediction> predictions;
    std::uint64_t left_starts=0,indexed_starts=0;
    ContextMatcher(const ContextUnits &source,int k,int maximum):left(source),minimum(k),cap(maximum) {
        if(k<2||k>13||maximum<k)throw std::runtime_error("Unsupported contextual seed/cap");
        for(const auto &u:source.units) {
            for(char c:u.text)if(c<'A'||c>'V')throw std::runtime_error("Hebrew rank outside 0..21");
            if(int(u.text.size())>minimum)left_starts+=2*(u.text.size()-minimum);
        }
        for(int di=0;di<2;++di)for(int ai=0;ai<4;++ai)for(int bi=0;bi<4;++bi)
        for(int u=0;u<int(source.units.size());++u) {
            auto h=source.units[u].text;if(di)std::reverse(h.begin(),h.end());
            std::string predicted;
            for(int j=0;j+1<int(h.size());++j)
                predicted+=char('A'+mod24(coefficients[ai]*(h[j]-'A')+coefficients[bi]*(h[j+1]-'A')));
            int pi=int(predictions.size());predictions.push_back({predicted,u,di?-1:1,(di*4+ai)*4+bi});
            for(int p=0;p+minimum<=int(predicted.size());++p) {
                if(++indexed_starts>10000000)throw std::runtime_error("Contextual indexed start resource guard exceeded");
                index[relative_key(predicted,p)].push_back({pi,p});
            }
        }
    }
    ContextResult scan(const ContextUnits &right,bool all_rules) const {
        ContextResult out;std::array<ContextGraph,768> graphs;
        for(int r=0;r<int(right.units.size());++r) {
            const auto &g=right.units[r].text;
            for(int p=0;p+minimum<=int(g.size());++p) {
                auto found=index.find(relative_key(g,p));if(found==index.end())continue;
                for(const auto &seed:found->second) {
                    if(++out.seed_pairs>1000000)throw std::runtime_error("Contextual compatible seed resource guard exceeded");
                    const auto &q=predictions[seed.unit];
                    int c=mod24(g[p]-q.text[seed.start]),rule=q.base*24+c;
                    int bound=std::min({cap,int(g.size())-p,int(q.text.size())-seed.start});
                    auto key=std::make_pair(left.groups[q.unit],right.groups[r]);
                    auto &graph=graphs[rule];auto old=graph.find(key);
                    if(old!=graph.end()&&old->second.maximum>=bound)continue;
                    int length=minimum;
                    while(length<bound&&mod24(q.text[seed.start+length]-'A'+c)==g[p+length]-'A')++length;
                    if(old==graph.end()||old->second.maximum<length)
                        graph[key]={seed.unit,seed.start,r,p,length};
                }
            }
        }
        for(int rule=0;rule<768;++rule) {
            const auto &graph=graphs[rule];if(graph.size()<3)continue;
            int upper=0;for(const auto &edge:graph)upper=std::max(upper,edge.second.maximum);
            for(int k=upper;k>=minimum;--k) {
                auto matching=context_matching(graph,k);if(matching.empty())continue;
                out.rule_scores[rule]=k;
                if(k>out.score){out.score=k;out.winners.clear();}
                if(k==out.score)out.winners[rule]=std::move(matching);
                break;
            }
            if(!all_rules&&out.score==cap)return out;
        }
        return out;
    }
};

#ifndef BIBLELAB_CONTEXTUAL_MATCH_NO_MAIN
int main(int argc,char **argv) {
    try {
        if(argc!=6)throw std::runtime_error("usage: contextual_match INPUT MIN CAP DRAWS SEED");
        std::ifstream input(argv[1]);int nl,nr;
        if(!(input>>nl>>nr)||nl<0||nr<0)throw std::runtime_error("Invalid contextual dimensions");
        std::string line;std::getline(input,line);auto left=context_read(input,nl),right=context_read(input,nr);
        while(std::getline(input,line))if(line.find_first_not_of(" \t\r")!=std::string::npos)throw std::runtime_error("Trailing contextual input");
        int minimum=std::stoi(argv[2]),cap=std::stoi(argv[3]),draws=std::stoi(argv[4]);
        if(draws<0)throw std::runtime_error("Negative draws");
        ContextMatcher matcher(left,minimum,cap);auto observed=matcher.scan(right,true);
        std::uint64_t right_starts=0;for(const auto &u:right.units)if(int(u.text.size())>=minimum)right_starts+=u.text.size()-minimum+1;
        std::cout<<"{\"score\":"<<observed.score<<",\"left_oriented_starts\":"<<matcher.left_starts
                 <<",\"indexed_source_starts\":"<<matcher.indexed_starts<<",\"right_starts\":"<<right_starts
                 <<",\"start_pairs\":"<<matcher.left_starts*right_starts
                 <<",\"formal_rule_start_pairs\":"<<matcher.left_starts*right_starts*384
                 <<",\"compatible_seed_pairs\":"<<observed.seed_pairs<<",\"rule_scores\":[";
        for(int i=0;i<768;++i){if(i)std::cout<<',';std::cout<<observed.rule_scores[i];}
        std::cout<<"],\"maximizing_rule_ids\":[";bool first=true;
        for(const auto &entry:observed.winners){if(!first)std::cout<<',';first=false;std::cout<<entry.first;}
        std::cout<<"],\"witnesses\":[";first=true;
        for(const auto &entry:observed.winners) {
            if(!first)std::cout<<',';first=false;int rule=entry.first,base=rule/24;
            std::cout<<"{\"rule_id\":"<<rule<<",\"a\":"<<coefficients[(base/4)%4]<<",\"b\":"<<coefficients[base%4]
                     <<",\"c\":"<<rule%24<<",\"direction\":"<<(base/16?-1:1)<<",\"hits\":[";
            bool first_hit=true;
            for(const auto &h:entry.second) {
                if(!first_hit)std::cout<<',';first_hit=false;const auto &q=matcher.predictions[h.prediction];
                int start=q.direction==1?h.start:int(left.units[q.unit].text.size())-h.start-observed.score-1;
                std::cout<<"{\"left_unit\":"<<q.unit<<",\"right_unit\":"<<h.right<<",\"direction\":"<<q.direction
                         <<",\"left_oriented_start\":"<<h.start<<",\"left_start\":"<<start
                         <<",\"left_end\":"<<start+observed.score+1<<",\"source_length\":"<<observed.score+1
                         <<",\"right_start\":"<<h.rstart<<",\"length\":"<<observed.score<<'}';
            }
            std::cout<<"]}";
        }
        std::cout<<"],\"reference_scores\":{";std::mt19937_64 rng(std::stoull(argv[5]));
        for(int mode=0;mode<2;++mode) {
            std::vector<int> scores;scores.reserve(draws);
            for(int i=0;i<draws;++i) {
                ContextUnits ref;
                if(mode==0){ref=right;ref.units=randomized(right.units,1,rng);}else ref=context_types(right,rng);
                scores.push_back(matcher.scan(ref,false).score);
                auto prefix=std::string(argv[1])+(mode==0?".words.":".word_types.");
                if(i==0)context_save(prefix+"first.txt",left,ref);
                if(i==draws-1)context_save(prefix+"last.txt",left,ref);
                if(draws>=2000&&(i+1)%2000==0)std::cerr<<"contextual reference mode "<<mode<<" draws "<<i+1<<'\n';
            }
            if(mode)std::cout<<',';std::cout<<(mode==0?"\"words\":" : "\"word_types\":");print_scores(scores);
        }
        std::cout<<"}}\n";
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
#endif
