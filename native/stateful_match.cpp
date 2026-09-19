// FAM-006: reset-at-window cumulative recurrence; no FAM-004 formula reuse.
#define BIBLELAB_CONTEXTUAL_MATCH_NO_MAIN
#include "contextual_match.cpp"
#undef BIBLELAB_CONTEXTUAL_MATCH_NO_MAIN

class StatefulMatcher {
    const ContextUnits &left;int minimum,cap;
    std::array<std::unordered_map<std::uint64_t,std::vector<Seed>>,4> index;
    std::array<std::vector<int>,4> sums;
    std::uint64_t source_key(const std::string &h,int start,int a,int bi) const {
        int z=0,first=0,b=coefficients[bi];std::uint64_t key=0;
        for(int i=0;i<minimum;++i) {
            z=mod24(a*(h[start+i]-'A')+b*z);
            if(i==0)first=z;else key=(key<<5)|unsigned(mod24(z-sums[bi][i]*first));
        }
        return key;
    }
    std::uint64_t greek_key(const std::string &g,int start,int bi) const {
        std::uint64_t key=0;int first=g[start]-'A';
        for(int i=1;i<minimum;++i)key=(key<<5)|unsigned(mod24(g[start+i]-'A'-sums[bi][i]*first));
        return key;
    }
public:
    std::vector<Prediction> sources;
    std::uint64_t left_starts=0,indexed_starts=0;
    StatefulMatcher(const ContextUnits &source,int k,int maximum):left(source),minimum(k),cap(maximum) {
        if(k<2||k>13||maximum<k)throw std::runtime_error("Unsupported stateful lengths");
        for(const auto &u:source.units) {
            for(char c:u.text)if(c<'A'||c>'V')throw std::runtime_error("Hebrew rank outside0..21");
            left_starts+=2*std::max(0,int(u.text.size())-minimum+1);
        }
        if(left_starts*16>5000000)throw std::runtime_error("Stateful indexed start resource guard exceeded");
        for(int bi=0;bi<4;++bi) {
            int s=0;for(int i=0;i<minimum;++i){s=mod24(1+coefficients[bi]*s);sums[bi].push_back(s);}
        }
        for(int di=0;di<2;++di)for(int ai=0;ai<4;++ai)for(int bi=0;bi<4;++bi)
        for(int u=0;u<int(source.units.size());++u) {
            auto h=source.units[u].text;if(di)std::reverse(h.begin(),h.end());
            int pi=int(sources.size());sources.push_back({h,u,di?-1:1,(di*4+ai)*4+bi});
            for(int start=0;start+minimum<=int(h.size());++start) {
                ++indexed_starts;index[bi][source_key(h,start,coefficients[ai],bi)].push_back({pi,start});
            }
        }
        if(indexed_starts!=left_starts*16)throw std::runtime_error("Stateful start accounting failed");
    }
    ContextResult scan(const ContextUnits &right,bool all_rules) const {
        ContextResult out;std::array<ContextGraph,768> graphs;
        for(int r=0;r<int(right.units.size());++r) {
            const auto &g=right.units[r].text;
            for(int start=0;start+minimum<=int(g.size());++start)for(int bi=0;bi<4;++bi) {
                auto found=index[bi].find(greek_key(g,start,bi));if(found==index[bi].end())continue;
                for(const auto &seed:found->second) {
                    if(++out.seed_pairs>5000000)throw std::runtime_error("Stateful compatible seed resource guard exceeded");
                    const auto &h=sources[seed.unit];int a=coefficients[(h.base/4)%4],b=coefficients[bi];
                    int c=mod24(g[start]-'A'-a*(h.text[seed.start]-'A')),rule=h.base*24+c;
                    int bound=std::min({cap,int(g.size())-start,int(h.text.size())-seed.start});
                    auto key=std::make_pair(left.groups[h.unit],right.groups[r]);auto &graph=graphs[rule];auto old=graph.find(key);
                    if(old!=graph.end()&&old->second.maximum>=bound)continue;
                    int length=minimum,state=g[start+minimum-1]-'A';
                    while(length<bound) {
                        state=mod24(a*(h.text[seed.start+length]-'A')+b*state+c);
                        if(state!=g[start+length]-'A')break;++length;
                    }
                    if(old==graph.end()||old->second.maximum<length)graph[key]={seed.unit,seed.start,r,start,length};
                }
            }
        }
        for(int rule=0;rule<768;++rule) {
            const auto &graph=graphs[rule];if(graph.size()<3)continue;
            int upper=0;for(const auto &e:graph)upper=std::max(upper,e.second.maximum);
            for(int k=upper;k>=minimum;--k) {
                auto matching=context_matching(graph,k);if(matching.empty())continue;
                out.rule_scores[rule]=k;if(k>out.score){out.score=k;out.winners.clear();}
                if(k==out.score)out.winners[rule]=std::move(matching);break;
            }
            if(!all_rules&&out.score==cap)return out;
        }
        return out;
    }
};

int main(int argc,char **argv) {
    try {
        if(argc!=6)throw std::runtime_error("usage: stateful_match INPUT MIN CAP DRAWS SEED");
        std::ifstream input(argv[1]);int nl,nr;
        if(!(input>>nl>>nr)||nl<0||nr<0)throw std::runtime_error("Invalid stateful dimensions");
        std::string line;std::getline(input,line);auto left=context_read(input,nl),right=context_read(input,nr);
        while(std::getline(input,line))if(line.find_first_not_of(" \t\r")!=std::string::npos)throw std::runtime_error("Trailing input");
        int minimum=std::stoi(argv[2]),cap=std::stoi(argv[3]),draws=std::stoi(argv[4]);
        if(draws<0)throw std::runtime_error("Negative draws");
        StatefulMatcher matcher(left,minimum,cap);auto observed=matcher.scan(right,true);
        std::uint64_t rs=0;for(const auto &u:right.units)rs+=std::max(0,int(u.text.size())-minimum+1);
        std::cout<<"{\"score\":"<<observed.score<<",\"left_oriented_starts\":"<<matcher.left_starts
            <<",\"indexed_source_starts\":"<<matcher.indexed_starts<<",\"right_starts\":"<<rs
            <<",\"right_seed_queries\":"<<4*rs<<",\"start_pairs\":"<<matcher.left_starts*rs
            <<",\"formal_rule_start_pairs\":"<<matcher.indexed_starts*rs*24
            <<",\"compatible_seed_pairs\":"<<observed.seed_pairs<<",\"rule_scores\":[";
        for(int r=0;r<768;++r){if(r)std::cout<<',';std::cout<<observed.rule_scores[r];}
        std::cout<<"],\"maximizing_rule_ids\":[";bool first=true;
        for(const auto &entry:observed.winners){if(!first)std::cout<<',';first=false;std::cout<<entry.first;}
        std::cout<<"],\"witnesses\":[";first=true;
        for(const auto &entry:observed.winners) {
            if(!first)std::cout<<',';first=false;int rule=entry.first,base=rule/24;
            std::cout<<"{\"rule_id\":"<<rule<<",\"a\":"<<coefficients[(base/4)%4]<<",\"b\":"<<coefficients[base%4]
                <<",\"c\":"<<rule%24<<",\"direction\":"<<(base<16?1:-1)<<",\"initial_state\":0,\"hits\":[";
            bool initial=true;
            for(const auto &hit:entry.second) {
                if(!initial)std::cout<<',';initial=false;const auto &source=matcher.sources[hit.prediction];
                int start=source.direction==1?hit.start:int(source.text.size())-hit.start-observed.score;
                std::cout<<"{\"left_unit\":"<<source.unit<<",\"right_unit\":"<<hit.right<<",\"direction\":"<<source.direction
                    <<",\"left_oriented_start\":"<<hit.start<<",\"left_start\":"<<start<<",\"left_end\":"<<start+observed.score
                    <<",\"source_length\":"<<observed.score<<",\"right_start\":"<<hit.rstart<<",\"length\":"<<observed.score<<'}';
            }
            std::cout<<"]}";
        }
        std::cout<<"],\"reference_scores\":{";std::mt19937_64 rng(std::stoull(argv[5]));
        for(int mode=0;mode<2;++mode) {
            std::vector<int> values;
            for(int i=0;i<draws;++i) {
                ContextUnits ref;if(mode==0){ref=right;ref.units=randomized(right.units,1,rng);}else ref=context_types(right,rng);
                values.push_back(matcher.scan(ref,false).score);
                auto prefix=std::string(argv[1])+(mode==0?".words.":".word_types.");
                if(i==0)context_save(prefix+"first.txt",left,ref);if(i==draws-1)context_save(prefix+"last.txt",left,ref);
                if(draws>=2000&&(i+1)%2000==0)std::cerr<<"stateful reference mode "<<mode<<" draws "<<i+1<<'\n';
            }
            if(mode)std::cout<<',';std::cout<<(mode==0?"\"words\":" : "\"word_types\":");print_scores(values);
        }
        std::cout<<"}}\n";
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
