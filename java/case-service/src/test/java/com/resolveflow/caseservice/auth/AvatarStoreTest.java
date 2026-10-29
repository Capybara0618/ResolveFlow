package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.*;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.file.Path;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class AvatarStoreTest {
    @TempDir
    Path directory;

    @Test
    void reencodesImageAndConstrictsDimensions() throws Exception {
        var source = new BufferedImage(800, 400, BufferedImage.TYPE_INT_RGB);
        var bytes = new ByteArrayOutputStream();
        ImageIO.write(source, "jpeg", bytes);
        var store = new AvatarStore(directory.toString());
        String id = store.save(bytes.toByteArray());
        var image = ImageIO.read(new ByteArrayInputStream(store.read(id)));
        assertThat(image.getWidth()).isEqualTo(256);
        assertThat(image.getHeight()).isEqualTo(256);
        assertThat(id).matches("[a-f0-9-]{36}");
    }

    @Test
    void rejectsNonImageOversizedAndTraversal() {
        var store = new AvatarStore(directory.toString());
        assertThatThrownBy(() -> store.save("<svg/>".getBytes())).isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> store.save(new byte[2 * 1024 * 1024 + 1])).isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> store.read("../../secret")).isInstanceOf(RuntimeException.class);
    }

    @Test
    void boundsDimensionsBeforeDecodingPixels() throws Exception {
        var bytes = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(4097, 1, BufferedImage.TYPE_INT_RGB), "png", bytes);
        assertThatThrownBy(() -> new AvatarStore(directory.toString()).save(bytes.toByteArray()))
                .isInstanceOf(RuntimeException.class);
    }
}
