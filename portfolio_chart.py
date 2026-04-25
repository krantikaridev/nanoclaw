import json
import matplotlib.pyplot as plt
from datetime import datetime
import os

def plot_portfolio():
    if not os.path.exists("portfolio_history.json"):
        print("❌ No data yet")
        return
    with open("portfolio_history.json") as f:
        history = json.load(f)
    
    times = [datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")) for entry in history]
    values = [entry["total_value"] for entry in history]
    
    plt.figure(figsize=(12, 6))
    plt.plot(times, values, marker='o', linestyle='-', color='blue', linewidth=2.5, markersize=5)
    plt.title('Nanoclaw Portfolio Value Over Time (V2.5.2)')
    plt.xlabel('Time')
    plt.ylabel('Total Value (USD)')
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    
    plt.annotate(f'Latest: ${values[-1]:.2f}', xy=(times[-1], values[-1]), xytext=(10, 10),
                 textcoords='offset points', arrowprops=dict(arrowstyle='->'))
    
    plt.tight_layout()
    plt.savefig('portfolio_chart.png', dpi=250, bbox_inches='tight')
    print(f"✅ Visual chart saved as portfolio_chart.png ({len(history)} data points)")
    print(f"Net change: ${values[-1] - values[0]:.2f} ({(values[-1] - values[0])/values[0]*100:.2f}%)")

if __name__ == "__main__":
    plot_portfolio()
