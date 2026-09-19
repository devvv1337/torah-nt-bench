// FAM-005. Reuse input/RNG and already verified group matching; not old grammar.
#define BIBLELAB_CONTEXTUAL_MATCH_NO_MAIN
#include "contextual_match.cpp"
#undef BIBLELAB_CONTEXTUAL_MATCH_NO_MAIN

constexpr int broad_co[5]={-2,-1,0,1,2};
const char *kind_names[3]={"pair","triple","product"};
struct Program {int kind,span,direction,a,b,t,product;};
std::vector<Program> programs() {
    std::vector<Program> out;
    for(int d:{1,-1})for(int a:coefficients)for(int b:coefficients)out.push_back({0,2,d,a,b,0,0});
    for(int d:{1,-1})for(int a:coefficients)for(int b:broad_co)for(int t:coefficients)out.push_back({1,3,d,a,b,t,0});
    for(int d:{1,-1})for(int p:{-1,1})for(int a:broad_co)for(int b:broad_co)out.push_back({2,2,d,a,b,0,p});
    if(out.size()!=292)throw std::runtime_error("Bad program catalog");return out;
}
void print_program(int rule,const Program &p) {
    std::cout<<"{\"rule_id\":"<<rule<<",\"kind\":\""<<kind_names[p.kind]<<"\",\"span\":"<<p.span
             <<",\"direction\":"<<p.direction<<",\"linear\":["<<p.a<<','<<p.b;
    if(p.span==3)std::cout<<','<<p.t;
    std::cout<<"],\"product\":"<<p.product<<",\"intercept\":"<<rule%24<<'}';
}
struct ProgramPrediction {std::string text;int source,base;};
struct ProgramResult {
    int score=0;std::array<int,3> sub{};std::array<int,7008> scores{};
    std::uint64_t seed_pairs=0;std::map<int,std::vector<ContextHit>> winners;
};
class ProgramMatcher {
    const ContextUnits &left;int minimum,cap;
    std::unordered_map<std::uint64_t,std::vector<Seed>> index;
    std::uint64_t signature(const std::string &s,int p) const {
        std::uint64_t key=0;for(int j=1;j<minimum;++j)key=(key<<5)|unsigned(mod24(s[p+j]-s[p]));return key;
    }
public:
    std::vector<Program> catalog=programs();std::vector<ProgramPrediction> predicted;
    std::array<std::uint64_t,3> starts_by_kind{};
    std::array<std::uint64_t,2> starts_by_span{};
    std::uint64_t indexed_starts=0;
    ProgramMatcher(const ContextUnits &source,int k,int maximum,int begin,int end):left(source),minimum(k),cap(maximum) {
        if(begin<0||begin>=end||end>292)throw std::runtime_error("Invalid program batch");
        if(k<2||k>13||maximum<k)throw std::runtime_error("Unsupported program lengths");
        for(const auto &u:source.units) {
            for(char c:u.text)if(c<'A'||c>'V')throw std::runtime_error("Hebrew rank outside 0..21");
            for(int span:{2,3})starts_by_span[span-2]+=2*std::max(0,int(u.text.size())-minimum-span+2);
        }
        for(int base=begin;base<end;++base)for(int u=0;u<int(source.units.size());++u) {
            const auto &p=catalog[base];auto s=source.units[u].text;if(p.direction<0)std::reverse(s.begin(),s.end());
            std::string q;
            for(int i=0;i+p.span<=int(s.size());++i) {
                int x=s[i]-'A',y=s[i+1]-'A';int rank=p.a*x+p.b*y+p.product*x*y;
                if(p.span==3)rank+=p.t*(s[i+2]-'A');q+=char('A'+mod24(rank));
            }
            int pi=int(predicted.size());predicted.push_back({q,u,base});
            for(int start=0;start+minimum<=int(q.size());++start) {
                if(++indexed_starts>10000000)throw std::runtime_error("Program indexed start resource guard exceeded");
                ++starts_by_kind[p.kind];index[signature(q,start)].push_back({pi,start});
            }
        }
    }
    ProgramResult scan(const ContextUnits &right,bool observation) const {
        ProgramResult result;std::vector<ContextGraph> graphs(7008);
        for(int r=0;r<int(right.units.size());++r) {
            const auto &g=right.units[r].text;
            for(int start=0;start+minimum<=int(g.size());++start) {
                auto bucket=index.find(signature(g,start));if(bucket==index.end())continue;
                for(const auto &seed:bucket->second) {
                    if(++result.seed_pairs>5000000)throw std::runtime_error("Program compatible seed resource guard exceeded");
                    const auto &q=predicted[seed.unit];int intercept=mod24(g[start]-q.text[seed.start]);
                    auto &graph=graphs[q.base*24+intercept];auto key=std::make_pair(left.groups[q.source],right.groups[r]);
                    int limit=std::min({cap,int(g.size())-start,int(q.text.size())-seed.start});auto old=graph.find(key);
                    if(old!=graph.end()&&old->second.maximum>=limit)continue;
                    int length=minimum;
                    while(length<limit&&mod24(q.text[seed.start+length]-'A'+intercept)==g[start+length]-'A')++length;
                    if(old==graph.end()||old->second.maximum<length)graph[key]={seed.unit,seed.start,r,start,length};
                }
            }
        }
        for(int rule=0;rule<7008;++rule) {
            int kind=catalog[rule/24].kind;if(!observation&&result.sub[kind]==cap)continue;
            const auto &graph=graphs[rule];if(graph.size()<3)continue;
            int maximum=0;for(const auto &e:graph)maximum=std::max(maximum,e.second.maximum);
            for(int length=maximum;length>=minimum;--length) {
                auto matching=context_matching(graph,length);if(matching.empty())continue;
                result.scores[rule]=length;result.sub[kind]=std::max(result.sub[kind],length);
                if(length>result.score){result.score=length;result.winners.clear();}
                if(length==result.score)result.winners[rule]=std::move(matching);
                break;
            }
        }
        return result;
    }
};

int main(int argc,char **argv) {
    try {
        if(argc==2&&std::string(argv[1])=="--catalog") {
            auto catalog=programs();std::cout<<'[';
            for(int rule=0;rule<7008;++rule){if(rule)std::cout<<',';print_program(rule,catalog[rule/24]);}
            std::cout<<"]\n";return 0;
        }
        if(argc!=8)throw std::runtime_error("usage: short_programs_batch INPUT MIN CAP DRAWS SEED BASE_BEGIN BASE_END");
        std::ifstream input(argv[1]);int nl,nr;
        if(!(input>>nl>>nr)||nl<0||nr<0)throw std::runtime_error("Invalid program dimensions");
        std::string line;std::getline(input,line);auto left=context_read(input,nl),right=context_read(input,nr);
        while(std::getline(input,line))if(line.find_first_not_of(" \t\r")!=std::string::npos)throw std::runtime_error("Trailing program input");
        int minimum=std::stoi(argv[2]),cap=std::stoi(argv[3]),draws=std::stoi(argv[4]);if(draws<0)throw std::runtime_error("Negative draws");
        int begin=std::stoi(argv[6]),end=std::stoi(argv[7]);
        ProgramMatcher matcher(left,minimum,cap,begin,end);auto observed=matcher.scan(right,true);
        std::uint64_t right_starts=0;for(const auto &u:right.units)right_starts+=std::max(0,int(u.text.size())-minimum+1);
        std::cout<<"{\"base_begin\":"<<begin<<",\"base_end\":"<<end<<",\"score\":"<<observed.score<<",\"indexed_source_starts\":"<<matcher.indexed_starts
                 <<",\"right_starts\":"<<right_starts<<",\"formal_program_start_pairs\":"<<matcher.indexed_starts*right_starts*24
                 <<",\"compatible_seed_pairs\":"<<observed.seed_pairs<<",\"left_oriented_starts_by_span\":{\"2\":"
                 <<matcher.starts_by_span[0]<<",\"3\":"<<matcher.starts_by_span[1]<<"},\"indexed_starts_by_kind\":{";
        for(int k=0;k<3;++k){if(k)std::cout<<',';std::cout<<'"'<<kind_names[k]<<"\":"<<matcher.starts_by_kind[k];}
        std::cout<<"},\"opcode_maxima\":{";
        for(int k=0;k<3;++k){if(k)std::cout<<',';std::cout<<'"'<<kind_names[k]<<"\":"<<observed.sub[k];}
        std::cout<<"},\"rule_scores\":[";
        for(int r=0;r<7008;++r){if(r)std::cout<<',';std::cout<<observed.scores[r];}
        std::cout<<"],\"maximizing_rule_ids\":[";bool first=true;
        for(const auto &entry:observed.winners){if(!first)std::cout<<',';first=false;std::cout<<entry.first;}
        std::cout<<"],\"witnesses\":[";first=true;
        for(const auto &entry:observed.winners) {
            if(!first)std::cout<<',';first=false;const auto &p=matcher.catalog[entry.first/24];
            std::cout<<"{\"program\":";print_program(entry.first,p);std::cout<<",\"hits\":[";bool first_hit=true;
            for(const auto &h:entry.second) {
                if(!first_hit)std::cout<<',';first_hit=false;const auto &q=matcher.predicted[h.prediction];
                int consumed=observed.score+p.span-1;
                int start=p.direction==1?h.start:int(left.units[q.source].text.size())-h.start-consumed;
                std::cout<<"{\"left_unit\":"<<q.source<<",\"right_unit\":"<<h.right<<",\"direction\":"<<p.direction
                         <<",\"left_oriented_start\":"<<h.start<<",\"left_start\":"<<start<<",\"left_end\":"<<start+consumed
                         <<",\"source_length\":"<<consumed<<",\"right_start\":"<<h.rstart<<",\"length\":"<<observed.score<<'}';
            }
            std::cout<<"]}";
        }
        std::cout<<"],\"reference_scores\":{";
        std::mt19937_64 rng(std::stoull(argv[5]));std::array<std::array<std::vector<int>,3>,2> subrefs;
        std::array<std::vector<int>,2> seedrefs;
        for(int mode=0;mode<2;++mode) {
            std::vector<int> scores;scores.reserve(draws);
            for(int i=0;i<draws;++i) {
                ContextUnits ref;if(mode==0){ref=right;ref.units=randomized(right.units,1,rng);}else ref=context_types(right,rng);
                auto result=matcher.scan(ref,false);scores.push_back(result.score);seedrefs[mode].push_back(static_cast<int>(result.seed_pairs));
                for(int k=0;k<3;++k)subrefs[mode][k].push_back(result.sub[k]);
                auto prefix=std::string(argv[1])+(mode==0?".words.":".word_types.");
                if(i==0)context_save(prefix+"first.txt",left,ref);
                if(i==draws-1)context_save(prefix+"last.txt",left,ref);
                if(draws>=2000&&(i+1)%2000==0)std::cerr<<"program reference mode "<<mode<<" draws "<<i+1<<'\n';
            }
            if(mode)std::cout<<',';std::cout<<(mode?"\"word_types\":" : "\"words\":");print_scores(scores);
        }
        std::cout<<"},\"reference_opcode_maxima\":{";
        for(int mode=0;mode<2;++mode) {
            if(mode)std::cout<<',';std::cout<<(mode?"\"word_types\":{" : "\"words\":{");
            for(int k=0;k<3;++k){if(k)std::cout<<',';std::cout<<'"'<<kind_names[k]<<"\":";print_scores(subrefs[mode][k]);}
            std::cout<<'}';
        }
        std::cout<<"},\"reference_seed_pairs\":{\"words\":";print_scores(seedrefs[0]);
        std::cout<<",\"word_types\":";print_scores(seedrefs[1]);std::cout<<"}}\n";
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
