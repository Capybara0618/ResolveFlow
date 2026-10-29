package com.resolveflow.caseservice.shopping;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.auth.AvatarStore;
import com.resolveflow.shared.shopping.PresentationWire.*;
import java.awt.image.BufferedImage;
import java.io.*;
import java.util.*;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.*;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.ObjectMapper;

@AutoConfigureRestTestClient
class PresentationApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    CommerceShoppingClient commerce;

    @Autowired
    AvatarStore files;

    final ObjectMapper json = new ObjectMapper();

    @TestConfiguration
    static class Configuration {
        @Bean
        @Primary
        CommerceShoppingClient client() {
            return mock(CommerceShoppingClient.class);
        }
    }

    @BeforeEach
    void prepare() {
        reset(commerce);
    }

    String login(String user, String pass) {
        return "Bearer "
                + json.readTree(rest.post()
                                .uri("/api/v1/auth/login")
                                .contentType(MediaType.APPLICATION_JSON)
                                .body(Map.of("username", user, "password", pass))
                                .exchange()
                                .expectStatus()
                                .isOk()
                                .expectBody(String.class)
                                .returnResult()
                                .getResponseBody())
                        .path("access_token")
                        .asString();
    }

    byte[] png() throws Exception {
        var out = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(800, 400, BufferedImage.TYPE_INT_RGB), "png", out);
        return out.toByteArray();
    }

    @Test
    void uploadedCatalogImagesAreOwnedPrivateUntilPublishedAndNeverExposeAccountAvatars() throws Exception {
        String owner = login("demo-admin", "demo-pass-1100"), other = login("demo-admin-m2", "demo-pass-2100");
        var parts = new MultipartBodyBuilder();
        parts.part("file", new ByteArrayResource(png()) {
                    @Override
                    public String getFilename() {
                        return "image.png";
                    }
                })
                .contentType(MediaType.IMAGE_PNG);
        var result = rest.post()
                .uri("/api/v1/merchant/media")
                .header("Authorization", owner)
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(parts.build())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        String id = json.readTree(result).path("media_id").asString();
        var raw = rest.get()
                .uri("/api/v1/merchant/media/" + id)
                .header("Authorization", owner)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(byte[].class)
                .returnResult()
                .getResponseBody();
        var image = ImageIO.read(new ByteArrayInputStream(raw));
        assertThat(image.getWidth()).isEqualTo(800);
        assertThat(image.getHeight()).isEqualTo(400);
        rest.get()
                .uri("/api/v1/merchant/media/" + id)
                .header("Authorization", other)
                .exchange()
                .expectStatus()
                .isNotFound();
        when(commerce.publishedMedia(id)).thenReturn(new Published(false));
        rest.get().uri("/api/v1/shop/media/" + id).exchange().expectStatus().isNotFound();
        when(commerce.publishedMedia(id)).thenReturn(new Published(true));
        rest.get().uri("/api/v1/shop/media/" + id).exchange().expectStatus().isOk();
        String avatar = files.save(png());
        rest.get().uri("/api/v1/shop/media/" + avatar).exchange().expectStatus().isNotFound();
        verify(commerce, never()).publishedMedia(avatar);
        var body = new ProductWrite(0L, List.of(id), List.of(), "", "");
        rest.post()
                .uri("/api/v1/merchant/products/P-2001/presentation")
                .header("Authorization", other)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isNotFound();
        verify(commerce, never()).savePresentation(anyString(), any());
    }
}
