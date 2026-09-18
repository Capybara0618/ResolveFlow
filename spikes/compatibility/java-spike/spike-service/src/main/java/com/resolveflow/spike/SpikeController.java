package com.resolveflow.spike;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.client.ServiceInstance;
import org.springframework.cloud.client.discovery.DiscoveryClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * Endpoints used by the T00 gates to prove discovery, Nacos config import and
 * gateway routing against real running processes.
 */
@RestController
@RequestMapping("/spike")
public class SpikeController {

    private final DiscoveryClient discoveryClient;

    /** Comes from Nacos config when the "nacos" profile is active, else from the default. */
    @Value("${spike.greeting:default-local-value}")
    private String greeting;

    @Value("${spring.application.name}")
    private String applicationName;

    private final SpikeFeignClient feignClient;

    public SpikeController(DiscoveryClient discoveryClient, SpikeFeignClient feignClient) {
        this.discoveryClient = discoveryClient;
        this.feignClient = feignClient;
    }

    /** Calls itself through OpenFeign + LoadBalancer, resolved via Nacos. */
    @GetMapping("/via-feign")
    public Map<String, Object> viaFeign() {
        Map<String, Object> down = feignClient.ping();
        return Map.of("feignReached", down.get("service"), "downstream", down);
    }

    @GetMapping("/ping")
    public Map<String, Object> ping() {
        return Map.of(
                "service", applicationName,
                "instance", System.getProperty("spike.instance.id", "unknown"),
                "greeting", greeting,
                "javaVersion", System.getProperty("java.version"));
    }

    /** Proves the Nacos config import actually delivered a value, not the local default. */
    @GetMapping("/config")
    public Map<String, Object> config() {
        return Map.of(
                "greeting", greeting,
                "fromNacosDefault", "default-local-value".equals(greeting));
    }

    @GetMapping("/discovery")
    public Map<String, Object> discovery() {
        List<String> services = discoveryClient.getServices();
        List<String> instances = discoveryClient.getInstances(applicationName).stream()
                .map(ServiceInstance::getUri)
                .map(Object::toString)
                .toList();
        return Map.of("services", services, "selfInstances", instances);
    }
}