package com.resolveflow.spike;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;

import java.util.Map;

/**
 * Proves OpenFeign + LoadBalancer + Nacos discovery resolve a service by name
 * (no hardcoded host/port) — the Java-to-Java call path the project depends on.
 */
@FeignClient(name = "spike-service")
public interface SpikeFeignClient {

    @GetMapping("/spike/ping")
    Map<String, Object> ping();
}