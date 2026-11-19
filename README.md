# System Głosowania Online (Kubernetes)

Aplikacja webowa umożliwiająca tworzenie, zarządzanie oraz przeprowadzanie głosowań online z podglądem wyników w czasie rzeczywistym (Server-Sent Events), wdrożona w klastrze Kubernetes (Minikube).

## Architektura i stos technologiczny
* **Backend & Frontend:** Python 3.11 (Flask, Gunicorn) + HTML5/JS (SSE)
* **Baza danych:** PostgreSQL 15 (wdrożona jako `StatefulSet` z trwałym wolumenem `PVC`/`PV`)
* **Orkiestracja i sieć:** Kubernetes (Ingress NGINX, Calico CNI, Metrics Server, HPA)

## Struktura repozytorium

### Katalog `app/` (Kod źródłowy aplikacji)
* `app/app.py` – główny kod aplikacji webowej (REST API, panel administratora, blokada wielokrotnego głosowania po ciasteczku sesyjnym oraz strumieniowanie wyników na żywo przez endpoint `/stream`).
* `app/requirements.txt` – lista zależności Pythona (`Flask`, `psycopg2-binary`, `gunicorn`).
* `app/Dockerfile` – definicja obrazu kontenera aplikacji oparta na `python:3.11-slim`.

### Katalog `k8s/` (Manifesty wdrożeniowe Kubernetes)
* `k8s/00-namespace-limits.yaml` – definicja wydzielonej przestrzeni nazw `voting-system` oraz limitów zasobów (`ResourceQuota` i `LimitRange`).
* `k8s/01-config-secret.yaml` – obiekty `ConfigMap` (parametry połączenia z bazą danych) oraz `Secret` (poufne poświadczenia bazy i token administratora).
* `k8s/02-postgres.yaml` – wdrożenie bazy danych PostgreSQL jako `StatefulSet` z dynamicznym szablonem wolumenu `PersistentVolumeClaim` (`1Gi`) oraz serwisem wewnętrznym `db-service` (`Headless Service`).
* `k8s/03-app.yaml` – wdrożenie aplikacji webowej (`Deployment` z 2 replikami, sondami `readinessProbe` oraz zdefiniowanymi `requests`/`limits`) wraz z serwisem `glosowanie-service` (`ClusterIP`).
* `k8s/04-ingress.yaml` – konfiguracja kontrolera `Ingress` wystawiającego aplikację pod domeną `glosowanie.local` z wydłużonym czasem timeoutu dla strumieni SSE.
* `k8s/05-hpa.yaml` – definicja `HorizontalPodAutoscaler` skalującego liczbę replik aplikacji od 2 do 6 przy przekroczeniu 50% utylizacji CPU.
* `k8s/06-networkpolicy.yaml` – reguła bezpieczeństwa sieciowego `NetworkPolicy` izolująca bazę danych (ruch przychodzący na port `5432` dozwolony wyłącznie z podów aplikacji).

## Szybkie uruchomienie lokalne (Minikube)

```bash
# 1. Uruchomienie klastra z obsługą NetworkPolicy, Ingress i HPA
minikube start --cni=calico --cpus=4 --memory=4096
minikube addons enable ingress
minikube addons enable metrics-server

# 2. Zbudowanie obrazu aplikacji w środowisku Dockera wewnątrz Minikube
eval $(minikube docker-env)
docker build -t voting-app:v1 ./app

# 3. Wdrożenie wszystkich manifestów Kubernetes
kubectl apply -f k8s/
