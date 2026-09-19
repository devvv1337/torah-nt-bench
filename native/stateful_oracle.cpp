// Independent Greek-difference transform, absolute keys and edge counting.
// Only independent input parsing and inclusion-exclusion are shared with this oracle.
#define SHORT_PROGRAM_ORACLE_NO_MAIN
#include "short_programs_oracle.cpp"
#undef SHORT_PROGRAM_ORACLE_NO_MAIN
int residue(int x){return (x%24+24)%24;}

int main(int argc,char **argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: stateful_oracle INPUT MIN CAP");
        int minimum=std::stoi(argv[2]),cap=std::stoi(argv[3]);
        if(minimum<1||minimum>12||cap<minimum)throw std::runtime_error("Bad oracle lengths");
        std::ifstream in(argv[1]);int nl,nr;if(!(in>>nl>>nr)||nl<0||nr<0)throw std::runtime_error("Bad dimensions");
        std::string line;std::getline(in,line);auto left=read_rows(in,nl,'V'),right=read_rows(in,nr,'X');
        while(std::getline(in,line))if(line.find_first_not_of(" \t\r")!=std::string::npos)throw std::runtime_error("Extra input");
        const int co[4]={-2,-1,1,2};std::array<int,768> scores{};std::uint64_t seeds=0;
        auto mask=(std::uint64_t(1)<<(minimum*5))-1;
        for(int bi=0;bi<4;++bi) {
            int b=co[bi];std::unordered_map<std::uint64_t,std::vector<std::pair<int,int>>> index;
            for(int r=0;r<nr;++r)for(int start=0;start+minimum<=int(right[r].text.size());++start) {
                const auto &g=right[r].text;std::uint64_t key=unsigned(g[start]-'A');
                for(int i=1;i<minimum;++i)key=(key<<5)|unsigned(residue(g[start+i]-'A'-b*(g[start+i-1]-'A')));
                index[key].push_back({r,start});
            }
            for(int di=0;di<2;++di)for(int ai=0;ai<4;++ai)for(int c=0;c<24;++c) {
                int a=co[ai],rule=(((di*4)+ai)*4+bi)*24+c;std::map<std::pair<int,int>,int> group_max;
                for(int l=0;l<nl;++l) {
                    auto h=left[l].text;if(di)std::reverse(h.begin(),h.end());std::vector<int> affine;
                    for(char x:h)affine.push_back(residue(a*(x-'A')+c));std::uint64_t key=0;
                    for(int end=0;end<int(h.size());++end) {
                        key=((key<<5)|unsigned(affine[end]))&mask;if(end+1<minimum)continue;
                        auto found=index.find(key);if(found==index.end())continue;int start=end+1-minimum;
                        for(auto pos:found->second) {
                            ++seeds;int r=pos.first,p=pos.second,length=minimum;const auto &g=right[r].text;
                            while(length<cap&&start+length<int(h.size())&&p+length<int(g.size())
                                &&affine[start+length]==residue(g[p+length]-'A'-b*(g[p+length-1]-'A')))++length;
                            auto edge=std::make_pair(left[l].group,right[r].group);group_max[edge]=std::max(group_max[edge],length);
                        }
                    }
                }
                std::vector<OracleEdge> edges;int upper=0;
                for(auto e:group_max){edges.push_back({e.first.first,e.first.second,e.second});upper=std::max(upper,e.second);}
                for(int k=upper;k>=minimum;--k)if(three_edges(edges,k)){scores[rule]=k;break;}
            }
        }
        int best=*std::max_element(scores.begin(),scores.end());std::cout<<"{\"score\":"<<best<<",\"compatible_seed_pairs\":"<<seeds<<",\"rule_scores\":[";
        for(int r=0;r<768;++r){if(r)std::cout<<',';std::cout<<scores[r];}
        std::cout<<"],\"maximizing_rule_ids\":[";bool first=true;
        for(int r=0;r<768;++r)if(best>0&&scores[r]==best){if(!first)std::cout<<',';first=false;std::cout<<r;}
        std::cout<<"]}\n";
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
