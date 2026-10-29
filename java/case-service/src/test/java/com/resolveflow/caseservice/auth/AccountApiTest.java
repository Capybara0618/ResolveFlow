package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.util.Map;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.ObjectMapper;

@AutoConfigureRestTestClient
class AccountApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    final ObjectMapper json = new ObjectMapper();

    @BeforeEach
    void account() {
        jdbc.update("INSERT IGNORE INTO platform_buyer(buyer_id) VALUES ('B-account-http-test')");
        jdbc.update("DELETE FROM identity_account WHERE username='account-http-test'");
        jdbc.update(
                "INSERT INTO identity_account(username,role,buyer_id,display_name,password_hash,identity_version) SELECT 'account-http-test',role,'B-account-http-test','测试资料',password_hash,1 FROM identity_account WHERE username='demo-buyer'");
    }

    String token(String user) {
        String result = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", user, "password", "demo-pass-4001"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return "Bearer " + json.readTree(result).path("access_token").asString();
    }

    @Test
    void multipartAvatarIsPersistedPrivateAndCanBeResetWithoutInvalidatingLogin() throws Exception {
        String auth = token("account-http-test");
        var buffer = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(400, 200, BufferedImage.TYPE_INT_RGB), "png", buffer);
        var parts = new MultipartBodyBuilder();
        parts.part("expected_version", "1");
        parts.part("file", new ByteArrayResource(buffer.toByteArray()) {
                    @Override
                    public String getFilename() {
                        return "avatar.png";
                    }
                })
                .contentType(MediaType.IMAGE_PNG);
        rest.post()
                .uri("/api/v1/account/avatar")
                .header("Authorization", auth)
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(parts.build())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.version")
                .isEqualTo(2)
                .jsonPath("$.avatar_id")
                .isNotEmpty();
        var image = rest.get()
                .uri("/api/v1/account/avatar")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isOk()
                .expectHeader()
                .valueEquals("Cache-Control", "private, no-store")
                .expectBody(byte[].class)
                .returnResult()
                .getResponseBody();
        assertThat(ImageIO.read(new java.io.ByteArrayInputStream(image)).getWidth())
                .isEqualTo(256);
        rest.get().uri("/api/v1/account/avatar").exchange().expectStatus().isUnauthorized();
        rest.get()
                .uri("/api/v1/account/avatar")
                .header("Authorization", token("demo-buyer"))
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.post()
                .uri("/api/v1/account/avatar/reset")
                .header("Authorization", auth)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("expected_version", 2))
                .exchange()
                .expectStatus()
                .isOk();
        rest.get()
                .uri("/api/v1/account/avatar")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.get()
                .uri("/api/v1/account/profile")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.version")
                .isEqualTo(3);
    }
}
