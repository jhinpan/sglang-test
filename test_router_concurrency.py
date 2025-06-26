#!/usr/bin/env python3
"""
SGLang router concurrency test - supports both direct worker and router modes
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import signal
from typing import Dict, Any, List, Optional

import aiohttp
import requests

# Configuration
DEFAULT_MODEL = "qwen/qwen2.5-0.5b-instruct"
CONCURRENCY_LEVELS = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 30000, 40000, 50000]

def kill_existing_sglang_processes():
    """Kill any existing SGLang processes"""
    import psutil
    killed = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if cmdline and any('sglang' in str(arg) for arg in cmdline):
                proc.kill()
                killed.append(proc.pid)
        except:
            pass
    if killed:
        print(f"Killed existing SGLang processes: {killed}")
        time.sleep(2)

def launch_worker_only(model_path: str, port: int = 31000) -> subprocess.Popen:
    """Launch worker directly without router"""
    cmd = [
        sys.executable, "-m", "sglang.launch_server",
        "--model-path", model_path,
        "--host", "0.0.0.0",
        "--port", str(port),
        "--max-total-tokens", "10000",
        "--mem-fraction-static", "0.9",
        "--disable-radix-cache",
        "--max-running-requests", "1024",
    ]
    
    print(f"Launching worker: {' '.join(cmd)}")
    process = subprocess.Popen(cmd)
    
    # Wait for worker to be ready
    start_time = time.time()
    while time.time() - start_time < 60:
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
            if resp.status_code == 200:
                print(f"✓ Worker ready on port {port}")
                return process
        except:
            pass
        time.sleep(2)
    
    raise RuntimeError("Worker failed to start")

def launch_router_with_dp(model_path: str, dp_size: int = 2, router_port: int = 30000) -> subprocess.Popen:
    """Launch router with data parallelism (co-launch mode)"""
    cmd = [
        sys.executable, "-m", "sglang_router.launch_server",
        "--model-path", model_path,
        "--host", "0.0.0.0",
        "--port", str(router_port),
        "--dp-size", str(dp_size),
        "--max-total-tokens", "10000",
        "--mem-fraction-static", "0.85",
        "--disable-radix-cache",
        "--max-running-requests", "2048",
        "--router-eviction-interval", "5",
        "--router-policy", "cache_aware",
    ]
    
    print(f"Launching router with {dp_size} workers: {' '.join(cmd)}")
    process = subprocess.Popen(cmd)
    
    # Wait for router to be ready
    start_time = time.time()
    while time.time() - start_time < 90:  # Give more time for multiple workers
        try:
            resp = requests.get(f"http://127.0.0.1:{router_port}/health", timeout=2)
            if resp.status_code == 200:
                print(f"✓ Router ready on port {router_port} with {dp_size} workers")
                return process
        except:
            pass
        time.sleep(3)
    
    raise RuntimeError("Router failed to start")

async def send_request(session: aiohttp.ClientSession, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a single request"""
    start_time = time.perf_counter()
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as response:
            # Handle different response types
            content_type = response.headers.get('Content-Type', '')
            
            if response.status == 200:
                # Try to parse as JSON first
                try:
                    if 'application/json' in content_type:
                        result = await response.json()
                    else:
                        # Try to parse text as JSON
                        text = await response.text()
                        result = json.loads(text)
                    
                    latency = time.perf_counter() - start_time
                    return {
                        "success": True,
                        "latency": latency,
                        "tokens": len(result.get("text", "").split()) if "text" in result else 0
                    }
                except json.JSONDecodeError:
                    # If JSON parsing fails, treat as error
                    latency = time.perf_counter() - start_time
                    return {
                        "success": False,
                        "latency": latency,
                        "error": f"Invalid JSON response with content-type: {content_type}"
                    }
            else:
                latency = time.perf_counter() - start_time
                return {
                    "success": False,
                    "latency": latency,
                    "error": f"HTTP {response.status}: {response.reason}"
                }
    except Exception as e:
        latency = time.perf_counter() - start_time
        return {
            "success": False,
            "latency": latency,
            "error": str(e)[:100]
        }

async def run_concurrency_test(url: str, concurrency: int, num_requests: int) -> Dict[str, Any]:
    """Run test at specific concurrency level"""
    print(f"\n=== Testing Concurrency: {concurrency} ===")
    
    payload = {
        "text": "Once upon a time",
        "sampling_params": {
            "max_new_tokens": 10,
            "temperature": 0.7
        }
    }
    
    # Limit actual concurrency
    semaphore = asyncio.Semaphore(concurrency)
    
    async def limited_request(session):
        async with semaphore:
            return await send_request(session, url, payload)
    
    # Run requests
    results = []
    async with aiohttp.ClientSession() as session:
        tasks = [limited_request(session) for _ in range(num_requests)]
        
        # Process with progress
        completed = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            completed += 1
            if completed % 10 == 0:
                print(f"  Progress: {completed}/{num_requests}")
    
    # Calculate stats
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    
    if successful:
        latencies = [r["latency"] for r in successful]
        latencies.sort()
        stats = {
            "concurrency": concurrency,
            "total_requests": num_requests,
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": len(successful) / num_requests,
            "avg_latency": sum(latencies) / len(latencies),
            "min_latency": latencies[0],
            "max_latency": latencies[-1],
            "p50_latency": latencies[len(latencies) // 2],
            "p90_latency": latencies[int(len(latencies) * 0.9)],
            "p99_latency": latencies[int(len(latencies) * 0.99)],
            "throughput_rps": len(successful) / sum(latencies) if sum(latencies) > 0 else 0
        }
    else:
        stats = {
            "concurrency": concurrency,
            "total_requests": num_requests,
            "successful": 0,
            "failed": len(failed),
            "success_rate": 0,
            "error_samples": [r.get("error", "Unknown") for r in failed[:3]]
        }
    
    print(f"  Success rate: {stats.get('success_rate', 0):.1%}")
    if successful:
        print(f"  Avg latency: {stats['avg_latency']:.3f}s")
        print(f"  P90 latency: {stats['p90_latency']:.3f}s")
        print(f"  Throughput: {stats['throughput_rps']:.1f} req/s")
    
    return stats

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--port", type=int, default=31000)
    parser.add_argument("--output", default="concurrency_results.json")
    parser.add_argument("--use-router", action="store_true", help="Use router with multiple workers")
    parser.add_argument("--dp-size", type=int, default=2, help="Data parallel size when using router")
    parser.add_argument("--router-port", type=int, default=30000, help="Router port when using router")
    args = parser.parse_args()
    
    # Clean up any existing processes
    kill_existing_sglang_processes()
    
    # Launch worker or router
    process = None
    results = []
    
    try:
        if args.use_router:
            # Launch router with multiple workers
            process = launch_router_with_dp(args.model, args.dp_size, args.router_port)
            url = f"http://127.0.0.1:{args.router_port}/generate"
            print(f"\nUsing router with {args.dp_size} workers")
        else:
            # Launch single worker
            process = launch_worker_only(args.model, args.port)
            url = f"http://127.0.0.1:{args.port}/generate"
            print(f"\nUsing single worker")
        
        # Warmup
        print("\nWarming up...")
        async with aiohttp.ClientSession() as session:
            warmup_tasks = [
                send_request(session, url, {"text": "Hello", "sampling_params": {"max_new_tokens": 5}})
                for _ in range(10)
            ]
            await asyncio.gather(*warmup_tasks)
        
        # Run tests
        for concurrency in CONCURRENCY_LEVELS:
            # Check health
            health_port = args.router_port if args.use_router else args.port
            try:
                health = requests.get(f"http://127.0.0.1:{health_port}/health", timeout=2)
                if health.status_code != 200:
                    print("Server unhealthy, stopping tests")
                    break
            except:
                print("Server not responding, stopping tests")
                break
            
            # Make the number of requests scale with concurrency for a meaningful test.
            # The number of requests will be at least 100, and at least equal to the concurrency level.
            num_requests = max(100, concurrency)
            print(f"Testing with {num_requests} total requests for concurrency level {concurrency}.")

            # Run test
            result = await run_concurrency_test(url, concurrency, num_requests)
            results.append(result)
            
            # Stop if too many failures
            if result.get("success_rate", 0) < 0.5 and concurrency > 10:
                print(f"\nStopping tests due to low success rate")
                break
    
    finally:
        # Save results
        output = {
            "timestamp": time.time(),
            "model": args.model,
            "mode": "router" if args.use_router else "direct",
            "dp_size": args.dp_size if args.use_router else 1,
            "results": results
        }
        
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        
        print(f"\nResults saved to {args.output}")
        
        # Print summary
        print("\n=== Summary ===")
        print(f"Mode: {'Router with ' + str(args.dp_size) + ' workers' if args.use_router else 'Direct worker'}")
        print(f"{'Concurrency':>12} {'Success':>8} {'Avg Latency':>12} {'P90 Latency':>12} {'Throughput':>12}")
        print("-" * 70)
        for r in results:
            if r.get("successful", 0) > 0:
                print(f"{r['concurrency']:>12} {r['success_rate']:>7.1%} {r['avg_latency']:>11.3f}s {r['p90_latency']:>11.3f}s {r['throughput_rps']:>10.1f}/s")
            else:
                print(f"{r['concurrency']:>12} {r['success_rate']:>7.1%} {'N/A':>12} {'N/A':>12} {'N/A':>12}")
        
        # Cleanup
        if process:
            print(f"\nShutting down {'router' if args.use_router else 'worker'}...")
            process.terminate()
            process.wait()

if __name__ == "__main__":
    asyncio.run(main())