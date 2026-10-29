"""Optional Matplotlib publication/export figures from actual metrics.csv."""
import argparse
import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser(); p.add_argument('--run',required=True); a=p.parse_args()
    root=Path(a.run); figures=root/'figures'; figures.mkdir(exist_ok=True)
    with (root/'metrics.csv').open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
    colors={'root_only':'#7b8495','graph_only':'#de8f45','expanded_fifo':'#aa74cf','tracepatch':'#15a999','full_scan':'#5086dc'}
    for qs in ('usage','uniform'):
        for delta in sorted(set(r['delta'] for r in rows)):
            for metric in ('overall_accuracy','stale_error_reuse'):
                fig,ax=plt.subplots(figsize=(7,4.2),layout='constrained')
                for method,color in colors.items():
                    selected=sorted((r for r in rows if r['query_set']==qs and r['delta']==delta and r['method']==method and r[metric] and r['budget']),key=lambda r:float(r['budget']))
                    if not selected: continue
                    x=[float(r['budget']) for r in selected]; y=[float(r[metric]) for r in selected]
                    lo=[float(r[metric+'_ci_low']) for r in selected]; hi=[float(r[metric+'_ci_high']) for r in selected]
                    ax.plot(x,y,'o-',label=method,color=color,linewidth=1.6)
                    ax.fill_between(x,lo,hi,color=color,alpha=.09)
                ax.set(xlabel='Verification budget (work units)',ylabel=metric.replace('_',' '),ylim=(-.03,1.03),title=f'{qs} queries | missing-edge rate {delta} | smoke')
                ax.grid(alpha=.2); ax.legend(fontsize=8,ncol=2)
                fig.savefig(figures/f'mpl_{qs}_{delta}_{metric}.png',dpi=180)
                plt.close(fig)
    print('Saved Matplotlib figures to',figures)


if __name__=='__main__': main()
