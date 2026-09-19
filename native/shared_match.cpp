// Reuse only the byte alphabet, seed signature, extension and exact RNG utilities.
#define BIBLELAB_LOCAL_MATCH_NO_MAIN
#include "local_match.cpp"
#undef BIBLELAB_LOCAL_MATCH_NO_MAIN
#include <map>
#include <set>
#include <tuple>

struct SharedSeed {int left,direction,start,right,rstart,maximum;};
struct TableHit {int seed;std::array<int,24> forward,backward;};
struct SharedResult {
    int score=0,levels=0;std::uint64_t seed_pairs=0,checks=0;
    std::vector<SharedSeed> witness;std::array<int,24> mapping;
    SharedResult(){mapping.fill(-1);}
};
struct Grouped {std::vector<Unit> units;std::vector<int> groups;};

Grouped read_grouped(std::istream &input,int count) {
    Grouped result;
    for(int i=0;i<count;++i) {
        std::string line;if(!std::getline(input,line))throw std::runtime_error("Missing grouped unit");
        std::istringstream row(line);int group;
        if(!(row>>group)||group<0)throw std::runtime_error("Invalid group");
        std::string rest;std::getline(row,rest);std::istringstream text(rest+'\n');
        result.groups.push_back(group);result.units.push_back(read_unit(text));
    }
    return result;
}

class SharedMatcher {
    std::vector<Oriented> oriented;
    const Grouped &left;int minimum,cap,distinct;
    std::unordered_map<std::uint64_t,std::vector<Seed>> index;
    bool compatible(const TableHit &a,const TableHit &b) const {
        for(int x=0;x<24;++x) {
            if(a.forward[x]>=0 && b.forward[x]>=0 && a.forward[x]!=b.forward[x])return false;
            if(a.backward[x]>=0 && b.backward[x]>=0 && a.backward[x]!=b.backward[x])return false;
        }
        return true;
    }
public:
    std::uint64_t left_starts=0;int alphabet_size=0;
    SharedMatcher(const Grouped &source,int k,int maximum):left(source),minimum(k),cap(maximum) {
        if(k<1||k>16||maximum<k)throw std::runtime_error("Unsupported shared seed/cap");
        std::set<char> alphabet;for(const auto &u:source.units)for(char c:u.text)alphabet.insert(c);
        alphabet_size=static_cast<int>(alphabet.size());distinct=std::min(8,alphabet_size);
        for(int direction:{1,-1})for(int u=0;u<int(source.units.size());++u) {
            auto text=source.units[u].text;if(direction==-1)std::reverse(text.begin(),text.end());
            int oi=static_cast<int>(oriented.size());oriented.push_back({text,u,direction});
            for(int p=0;p+k<=int(text.size());++p){index[shape(text,p,k)].push_back({oi,p});++left_starts;}
        }
    }
    SharedResult scan(const Grouped &right) const {
        SharedResult out;std::vector<SharedSeed> seeds;
        for(int r=0;r<int(right.units.size());++r) {
            const auto &b=right.units[r].text;
            for(int j=0;j+minimum<=int(b.size());++j) {
                auto bucket=index.find(shape(b,j,minimum));if(bucket==index.end())continue;
                for(const auto &s:bucket->second) {
                    if(++out.seed_pairs>1000000)throw std::runtime_error("Shared compatible seed resource guard exceeded");
                    const auto &a=oriented[s.unit];int length=extend(a.text,s.start,b,j,cap);
                    if(length<minimum)throw std::runtime_error("Shared signature disagreement");
                    seeds.push_back({a.unit,a.direction,s.start,r,j,length});
                }
            }
        }
        std::sort(seeds.begin(),seeds.end(),[](const auto &a,const auto &b){
            return std::tie(a.left,a.start,a.right,a.rstart,a.direction)<std::tie(b.left,b.start,b.right,b.rstart,b.direction);});
        for(int k=cap;k>=minimum;--k) {
            ++out.levels;
            for(int direction:{1,-1}) {
                std::vector<TableHit> hits;std::set<int> lg,rg;
                for(int si=0;si<int(seeds.size());++si) {
                    const auto &s=seeds[si];if(s.maximum<k||s.direction!=direction)continue;
                    TableHit h;h.seed=si;h.forward.fill(-1);h.backward.fill(-1);int symbols=0;
                    const auto &a=oriented[(direction==1?0:static_cast<int>(left.units.size()))+s.left].text;
                    const auto &b=right.units[s.right].text;
                    for(int p=0;p<k;++p) {
                        int x=a[s.start+p]-'A',y=b[s.rstart+p]-'A';
                        symbols+=h.forward[x]<0;h.forward[x]=y;h.backward[y]=x;
                    }
                    if(symbols<distinct)continue;
                    hits.push_back(h);lg.insert(left.groups[s.left]);rg.insert(right.groups[s.right]);
                }
                if(lg.size()<3||rg.size()<3)continue;
                std::vector<std::vector<int>> lower(hits.size());
                for(int i=0;i<int(hits.size());++i)for(int j=i+1;j<int(hits.size());++j) {
                    if(++out.checks>50000000)throw std::runtime_error("Shared compatibility resource guard exceeded");
                    const auto &a=seeds[hits[i].seed];const auto &b=seeds[hits[j].seed];
                    if(left.groups[a.left]==left.groups[b.left]||right.groups[a.right]==right.groups[b.right]||!compatible(hits[i],hits[j]))continue;
                    std::size_t x=0,y=0;int common=-1;
                    while(x<lower[i].size() && y<lower[j].size()) {
                        if(lower[i][x]==lower[j][y]){common=lower[i][x];break;}
                        if(lower[i][x]<lower[j][y])++x;else ++y;
                    }
                    if(common>=0) {
                        out.score=k;
                        for(int h:{common,i,j}) {
                            out.witness.push_back(seeds[hits[h].seed]);
                            for(int c=0;c<24;++c)if(hits[h].forward[c]>=0)out.mapping[c]=hits[h].forward[c];
                        }
                        return out;
                    }
                    lower[j].push_back(i);
                }
            }
        }
        return out;
    }
};

Grouped randomize_types(const Grouped &source,std::mt19937_64 &rng) {
    std::map<std::size_t,std::set<std::string>> unique;
    for(const auto &u:source.units)for(const auto &w:u.words)unique[w.size()].insert(w);
    std::unordered_map<std::string,std::string> substitution;
    for(const auto &entry:unique) {
        std::vector<std::string> original(entry.second.begin(),entry.second.end()),permuted=original;
        shuffle_exact(permuted,rng);
        for(std::size_t i=0;i<original.size();++i)substitution[original[i]]=permuted[i];
    }
    auto result=source;
    for(auto &u:result.units){for(auto &w:u.words)w=substitution.at(w);u.text=join(u.words);}
    return result;
}

void save_reference(const std::string &path,const Grouped &left,const Grouped &right) {
    std::ofstream output(path);if(!output)throw std::runtime_error("Cannot archive reference input");
    output<<left.units.size()<<' '<<right.units.size()<<'\n';
    for(const auto *side:{&left,&right})for(std::size_t i=0;i<side->units.size();++i) {
        output<<side->groups[i];for(const auto &word:side->units[i].words)output<<' '<<word;output<<'\n';
    }
    if(!output)throw std::runtime_error("Cannot finish reference archive");
}

int main(int argc,char **argv) {
    try {
        if(argc!=6)throw std::runtime_error("usage: shared_match INPUT MIN CAP DRAWS SEED");
        std::ifstream input(argv[1]);int nl,nr;
        if(!(input>>nl>>nr)||nl<0||nr<0)throw std::runtime_error("Invalid shared dimensions");
        std::string line;std::getline(input,line);auto left=read_grouped(input,nl),right=read_grouped(input,nr);
        while(std::getline(input,line))if(line.find_first_not_of(" \t\r")!=std::string::npos)throw std::runtime_error("Trailing shared input");
        int minimum=std::stoi(argv[2]),cap=std::stoi(argv[3]),draws=std::stoi(argv[4]);if(draws<0)throw std::runtime_error("Negative draws");
        SharedMatcher matcher(left,minimum,cap);auto observed=matcher.scan(right);std::uint64_t right_starts=0;
        for(const auto &u:right.units)if(int(u.text.size())>=minimum)right_starts+=u.text.size()-minimum+1;
        std::cout<<"{\"score\":"<<observed.score<<",\"source_alphabet_size\":"<<matcher.alphabet_size
                 <<",\"left_oriented_starts\":"<<matcher.left_starts<<",\"right_starts\":"<<right_starts
                 <<",\"start_pairs\":"<<matcher.left_starts*right_starts<<",\"compatible_seed_pairs\":"<<observed.seed_pairs
                 <<",\"tested_lengths\":"<<observed.levels<<",\"compatibility_checks\":"<<observed.checks<<",\"witness\":[";
        for(std::size_t i=0;i<observed.witness.size();++i) {
            if(i)std::cout<<',';const auto &h=observed.witness[i];int start=h.direction==1?h.start:int(left.units[h.left].text.size())-h.start-observed.score;
            std::cout<<"{\"left_unit\":"<<h.left<<",\"right_unit\":"<<h.right<<",\"direction\":"<<h.direction
                     <<",\"left_oriented_start\":"<<h.start<<",\"left_start\":"<<start<<",\"left_end\":"<<start+observed.score
                     <<",\"right_start\":"<<h.rstart<<",\"length\":"<<observed.score<<'}';
        }
        std::cout<<"],\"mapping\":[";bool first=true;
        for(int x=0;x<24;++x)if(observed.mapping[x]>=0){if(!first)std::cout<<',';first=false;std::cout<<'['<<x<<','<<observed.mapping[x]<<']';}
        std::cout<<"],\"reference_scores\":{";std::mt19937_64 rng(std::stoull(argv[5]));
        for(int mode=0;mode<2;++mode) {
            std::vector<int> scores;scores.reserve(draws);
            for(int i=0;i<draws;++i) {
                Grouped reference;
                if(mode==0){reference=right;reference.units=randomized(right.units,1,rng);}
                else reference=randomize_types(right,rng);
                scores.push_back(matcher.scan(reference).score);
                std::string prefix=std::string(argv[1])+(mode==0?".words.":".word_types.");
                if(i==0)save_reference(prefix+"first.txt",left,reference);
                if(i==draws-1)save_reference(prefix+"last.txt",left,reference);
                if(draws>=2000 && (i+1)%2000==0)std::cerr<<"shared reference mode "<<mode<<" draws "<<i+1<<'\n';
            }
            if(mode)std::cout<<',';std::cout<<(mode==0?"\"words\":" : "\"word_types\":");print_scores(scores);
        }
        std::cout<<"}}\n";
    } catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
