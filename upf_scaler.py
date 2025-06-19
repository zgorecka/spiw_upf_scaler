import subprocess
import requests
import time
import yaml
import sys
import json

PROMETHEUS_ADDR = "http://192.168.2.64:9090"
SCAN_INTERVAL = 30  # sekundy
INTENT_FILE = "intent.yaml"
DEFAULT_NAMESPACE_CMD = "kubectl config view --minify --output jsonpath={..namespace}"
UPF_POD_NAME = "open5gs-upf"
UPF_CONTAINER_NAME = "open5gs-upf"

def get_namespace():
    return "open5gs"

def load_intent():
    with open(INTENT_FILE, 'r') as f:
        return yaml.safe_load(f)

def get_amf_sessions(namespace):
    query = f'amf_session{{service="open5gs-amf-metrics",namespace="open5gs"}}'
    try:
        resp = requests.get(f"{PROMETHEUS_ADDR}/api/v1/query", params={"query": query})
        data = resp.json()
        return int(float(data["data"]["result"][0]["value"][1]))
    except Exception as e:
        print(f"[!] Błąd pobierania metryki: {e}")
        return None

def find_cpu_limit(amf_sessions, intent_rules):
    for rule in intent_rules:
        if amf_sessions < rule['threshold']:
            return rule['cpu']
    return intent_rules[-1]['cpu']

def patch_upf(namespace, cpu_limit):
    pods = subprocess.check_output(["kubectl", "get", "pods", "-n", namespace], text=True)
    pod_name = next((line.split()[0] for line in pods.splitlines() if UPF_POD_NAME in line), None)
    if not pod_name:
        print("[!] Nie znaleziono poda UPF.")
        return

    patch = {
        "spec": {
            "containers": [
                {
                    "name": UPF_CONTAINER_NAME,
                    "resources": {
                        "limits": {"cpu": cpu_limit}
                    }
                }
            ]
        }
    }

    patch_json = json.dumps(patch)
    subprocess.run(["kubectl", "patch", "pod", pod_name, "--subresource", "resize",
                    "-n", namespace, "--patch", patch_json])
    print(f"[+] Zmieniono limit CPU na {cpu_limit} dla poda {pod_name}")

def main():
    args = sys.argv[1:]
    max_iter = 5
    namespace = get_namespace()

    if args:
        if args[0].isdigit():
            max_iter = int(args[0])
            if len(args) > 1:
                namespace = args[1]
        else:
            namespace = args[0]

    intent = load_intent()
    rules = intent.get("rules", [])

    print(f"[~] Start kontrolera, namespace: {namespace}, max_iter: {max_iter if max_iter > 0 else 'oo'}")

    i = 0
    while max_iter == -1 or i < max_iter:
        i += 1
        print(f"\n[#] Iteracja {i}")
        sessions = get_amf_sessions(namespace)
        if sessions is not None:
            cpu = find_cpu_limit(sessions, rules)
            print(f"[~] Sesje: {sessions}, przydzielane CPU: {cpu}")
            patch_upf(namespace, cpu)
        else:
            print("[!] Nie udało się pobrać sesji")

        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()