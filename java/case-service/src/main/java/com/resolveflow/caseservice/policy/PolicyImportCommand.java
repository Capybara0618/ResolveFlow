package com.resolveflow.caseservice.policy;

import java.nio.file.Path;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.stereotype.Component;

/**
 * The controlled import command (docs/core-contracts.md:53).
 *
 * <p>Policy management is not an HTTP surface on purpose: the three management routes were dropped from the
 * core contract, and a rule set is published by running this against the service's own database. It exists
 * only when {@code resolveflow.policy.import-dir} is set, so the ordinary service never imports anything on
 * start-up — a service that quietly changed policy when it booted would make policy a function of deploys.
 *
 * <p>The exit code is the point of it: an import that refused a file must not look like success to whoever
 * ran it in a pipeline.
 */
@Component
@ConditionalOnProperty(name = "resolveflow.policy.import-dir")
public class PolicyImportCommand implements ApplicationRunner {

    private static final Logger LOG = LoggerFactory.getLogger(PolicyImportCommand.class);

    private final PolicyImportService imports;
    private final ConfigurableApplicationContext context;

    public PolicyImportCommand(PolicyImportService imports, ConfigurableApplicationContext context) {
        this.imports = imports;
        this.context = context;
    }

    @Override
    public void run(ApplicationArguments args) {
        Path directory = Path.of(context.getEnvironment().getProperty("resolveflow.policy.import-dir", "."));
        int exitCode;
        try {
            PolicyImportService.Report report = imports.importDirectory(directory);
            LOG.info("policy import: {}", report.describe());
            exitCode = 0;
        } catch (PolicySourceReader.InvalidBundleException | PolicyImportService.ImportRefusedException error) {
            LOG.error("policy import refused: {}", error.getMessage());
            exitCode = 1;
        }
        int status = exitCode;
        System.exit(SpringApplication.exit(context, () -> status));
    }
}
